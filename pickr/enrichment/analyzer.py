"""
Pickr AI - Lead Analyzer (v2)
Spec steps 31-41: Build prompt, call AI with strict JSON, validate schema,
repair retry if invalid. Classify replies with strict JSON.
"""
import json
import uuid
import logging
from typing import Optional
from anthropic import Anthropic
from pydantic import ValidationError
from pickr.config import ANTHROPIC_API_KEY, LLM_MODEL, MAX_REPAIR_RETRIES, SCHEMA_VERSION
from pickr.models import LeadClassifierOutput, ReplyClassifierOutput

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


CLASSIFIER_PROMPT = """You are a wholesale lead qualification analyst for Pickr, a wholesale distributor
of premium branded products at 45-75% off retail.

Analyze the following scraped storefront data and return a STRICT JSON object.
DO NOT include any text outside the JSON. Only return the JSON object.

Scraped signals:
- Platform: {platform}
- Categories: {categories}
- Brand mentions: {brands}
- SKU estimate: {sku_count}
- Price range: ${price_min} - ${price_max}
- Site excerpt: {excerpt}
- MAP text found: {map_found}
- Company: {company_name}
- Niche: {niche}

Return this exact JSON schema:
{{
    "brand_list": ["cleaned brand names found"],
    "private_label_ratio": 0.0 to 1.0,
    "price_tier": "luxury" | "mid" | "discount" | "mixed",
    "scale_score": 0 to 100,
    "map_behavior_score": 0 to 100,
    "store_count": integer,
    "qualifies": true | false,
    "disqualify_reason": null | "private_label_only" | "arbitrage_no_scale" | "unknown"
}}

Rules:
- scale_score: 0=tiny/dropship, 50=medium, 100=large multi-location
- map_behavior_score: 0=no MAP respect, 50=some, 100=strict MAP compliance
- qualifies: false ONLY if private_label_only or arbitrage_no_scale
- brand_list: only real brand names, not the store's own name
- private_label_ratio: fraction of products that are the store's own brand"""


REPLY_CLASSIFIER_PROMPT = """You are classifying an inbound email reply from a wholesale lead.
Context: {context}

Reply text:
{reply_text}

Return STRICT JSON only:
{{
    "classification": "interested" | "objection" | "not_interested" | "unsubscribe" | "out_of_office" | "unknown",
    "objection_type": null | "catalog_request" | "pricing" | "margins" | "already_have_supplier" | "not_interested" | "timing" | "identity" | "minimums" | "authenticity" | "MAP" | "samples" | "returns" | "need_approval" | "already_stocked" | "too_many_brands" | "cash_flow" | "slow_season" | "legal_concerns" | "website_only" | "small_business" | "send_email_info",
    "action": "send_calendar" | "send_curated_catalog" | "suppress" | "handoff_to_human",
    "interest_level": 1 to 10
}}

Rules:
- If they say "remove me" / "unsubscribe" / "stop emailing" → classification: "unsubscribe", action: "suppress"
- If they show interest / want to talk / ask for time → classification: "interested", action: "send_calendar"
- If they have an objection but are engaging → classify the objection_type, action: "send_curated_catalog" or "handoff_to_human"
- If clearly not interested → classification: "not_interested", action: "handoff_to_human"
- interest_level: 1=hostile, 5=neutral, 10=very interested"""


def classify_lead(
    signals: dict,
    company_name: str,
    niche: Optional[str] = None,
) -> tuple[LeadClassifierOutput, str]:
    """
    Classify a lead using AI with strict JSON schema.
    Returns (parsed_output, llm_call_id).
    Spec: strict JSON or fail. One repair retry.
    """
    if not client:
        logger.warning("No Anthropic API key. Returning default classification.")
        return LeadClassifierOutput(), "no-api-key"

    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    prompt = CLASSIFIER_PROMPT.format(
        platform=signals.get("detected_platform", "unknown"),
        categories=signals.get("categories", []),
        brands=signals.get("brand_mentions_raw", []),
        sku_count=signals.get("sku_count_estimate", 0),
        price_min=signals.get("price_range_min", "?"),
        price_max=signals.get("price_range_max", "?"),
        excerpt=(signals.get("site_excerpt") or "")[:1000],
        map_found=signals.get("map_text_found", False),
        company_name=company_name,
        niche=niche or "unknown",
    )

    # Step 33: AI call
    raw_text = _call_llm(prompt, llm_call_id)

    # Step 34: JSON parse
    parsed = _parse_strict_json(raw_text)

    if parsed is None:
        # Step 36: Repair retry
        logger.warning(f"JSON parse failed for {llm_call_id}. Attempting repair.")
        repair_prompt = (
            f"Your previous output was not valid JSON. Here is what you returned:\n"
            f"{raw_text}\n\n"
            f"Please return ONLY a valid JSON object matching this schema:\n"
            f'{{"brand_list":[],"private_label_ratio":0.0,"price_tier":"mixed",'
            f'"scale_score":0,"map_behavior_score":0,"store_count":0,'
            f'"qualifies":true,"disqualify_reason":null}}'
        )
        raw_text = _call_llm(repair_prompt, f"{llm_call_id}-repair")
        parsed = _parse_strict_json(raw_text)

    if parsed is None:
        logger.error(f"JSON repair also failed for {llm_call_id}. Returning default.")
        return LeadClassifierOutput(), llm_call_id

    # Step 35: Schema validate via Pydantic
    try:
        output = LeadClassifierOutput(**parsed)
        return output, llm_call_id
    except ValidationError as e:
        logger.error(f"Schema validation failed for {llm_call_id}: {e}")
        return LeadClassifierOutput(), llm_call_id


def classify_reply(
    reply_text: str,
    context: str,
) -> tuple[ReplyClassifierOutput, str]:
    """
    Classify a reply using AI with strict JSON schema.
    Returns (parsed_output, llm_call_id).
    """
    if not client:
        return ReplyClassifierOutput(
            classification="unknown", action="handoff_to_human"
        ), "no-api-key"

    llm_call_id = f"llm-{uuid.uuid4().hex[:12]}"

    prompt = REPLY_CLASSIFIER_PROMPT.format(
        context=context,
        reply_text=reply_text,
    )

    raw_text = _call_llm(prompt, llm_call_id)
    parsed = _parse_strict_json(raw_text)

    if parsed is None:
        repair_prompt = (
            f"Your previous output was not valid JSON:\n{raw_text}\n\n"
            f"Return ONLY valid JSON: "
            f'{{"classification":"unknown","objection_type":null,'
            f'"action":"handoff_to_human","interest_level":5}}'
        )
        raw_text = _call_llm(repair_prompt, f"{llm_call_id}-repair")
        parsed = _parse_strict_json(raw_text)

    if parsed is None:
        return ReplyClassifierOutput(
            classification="unknown", action="handoff_to_human"
        ), llm_call_id

    try:
        output = ReplyClassifierOutput(**parsed)
        return output, llm_call_id
    except ValidationError:
        return ReplyClassifierOutput(
            classification="unknown", action="handoff_to_human"
        ), llm_call_id


def _call_llm(prompt: str, call_id: str) -> str:
    """Call Claude API and return raw text response."""
    logger.info(f"LLM call [{call_id}]: {len(prompt)} chars")
    try:
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"LLM call failed [{call_id}]: {e}")
        return ""


def _parse_strict_json(text: str) -> Optional[dict]:
    """Parse strict JSON from LLM output. No commentary allowed."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # Try finding JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None
