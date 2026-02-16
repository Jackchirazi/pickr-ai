"""
Pickr AI - Email Generation Engine (v2)
Spec steps 52-57: Build vars, render template, lint, persist.
High Authority Executive voice. Short confident paragraphs only.
"""
import uuid
import logging
from typing import Optional
from anthropic import Anthropic
from pickr.config import (
    ANTHROPIC_API_KEY, LLM_MODEL, BOOKING_LINK,
    MEETING_TITLE_TEMPLATE, MEETING_DAYS, MEETING_HOURS,
    MEETING_DURATION, MAX_BRANDS_PER_EMAIL,
)
from pickr.engine.linter import EmailLinter

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
linter = EmailLinter()

PERSONALITY_SYSTEM = """You are writing emails for Pickr, a wholesale distributor of premium brands
at deep discounts. Your persona is a High Authority Executive:
- Calm, strategic, direct, confident
- Short paragraphs, no fluff, no filler
- Under 120 words for cold emails, under 80 for replies
- Never sound desperate or salesy
- Never reveal cost basis, margins, full catalog, pricing details
- Always position as curated opportunity, not mass sales pitch
- Every objection response ends with the calendar link
- Reference specific store details from scraper signals when possible
- Store references must be traceable to scraped data or omitted"""

TOUCH_FRAMEWORKS = {
    1: "Cold intro. Mention something specific about their store. Introduce Pickr as curated sourcing. End with calendar link.",
    2: "Follow-up. Quick and casual. Reference touch 1. Maybe mention a specific brand relevant to them. Calendar link.",
    3: "Value add. Share a brief insight about their niche/market. Position meeting as next step. Calendar link.",
    4: "Social proof. Reference types of retailers you work with (not names). Quick meeting push. Calendar link.",
    5: "Last touch. Respectful. Quick note that you're available if timing ever changes. Calendar link. No breakup energy.",
}


def generate_email(
    company_name: str,
    niche: str,
    primary_angle: str,
    touch_number: int,
    brand_names: list[str],
    site_excerpt: Optional[str] = None,
    categories: Optional[list[str]] = None,
) -> dict:
    """
    Generate an email for a lead.
    Returns {subject, body} or raises on lint failure.
    """
    framework = TOUCH_FRAMEWORKS.get(touch_number, TOUCH_FRAMEWORKS[1])

    # Enforce brand cap
    brands_to_mention = brand_names[:MAX_BRANDS_PER_EMAIL]

    prompt = f"""Write a cold email for this lead:
Company: {company_name}
Niche: {niche}
Leverage angle: {primary_angle}
Touch: {touch_number} of 5
Framework: {framework}
Brands to mention (max {MAX_BRANDS_PER_EMAIL}): {', '.join(brands_to_mention) if brands_to_mention else 'none specific'}
Store categories: {', '.join(categories or [])}
Store excerpt (for specific references): {(site_excerpt or '')[:500]}
Calendar link: {BOOKING_LINK}
Meeting: {MEETING_DURATION}, {MEETING_DAYS}, {MEETING_HOURS}

Return ONLY a JSON object:
{{"subject": "email subject line", "body": "email body text"}}

Rules:
- Under 120 words for body
- Short paragraphs
- End with calendar link
- No cost/margin/pricing details
- No full catalog mentions
- Reference something specific from their store if possible"""

    if not client:
        return {
            "subject": f"{company_name} — quick brand sourcing idea",
            "body": f"Hi,\n\nNoticed your {niche} catalog. We source premium brands at competitive terms.\n\nWorth a quick chat?\n\n{BOOKING_LINK}",
        }

    try:
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=512,
            system=PERSONALITY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # Parse JSON response
        import json
        parsed = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

        if parsed and "subject" in parsed and "body" in parsed:
            # Step 56: Forbidden phrase lint
            lint_result = linter.lint(
                parsed["subject"],
                parsed["body"],
                brand_count=len(brands_to_mention),
            )
            if not lint_result["ok"]:
                logger.warning(f"Email lint failed: {lint_result}")
                # Return a safe fallback
                return {
                    "subject": f"{company_name} — curated brand opportunity",
                    "body": f"Hi,\n\nWe source premium brands relevant to your {niche} business.\n\nWorth a quick call?\n\n{BOOKING_LINK}",
                }
            return parsed
        else:
            logger.warning("Email generation returned invalid JSON")

    except Exception as e:
        logger.error(f"Email generation failed: {e}")

    return {
        "subject": f"{company_name} — quick brand sourcing idea",
        "body": f"Hi,\n\nNoticed your {niche} catalog. We source premium brands at competitive terms.\n\nWorth a quick chat?\n\n{BOOKING_LINK}",
    }


def generate_interest_response(company_name: str) -> dict:
    """Generate response for interested lead. Always includes calendar."""
    return {
        "subject": f"Re: {company_name}",
        "body": (
            f"Perfect.\n\n"
            f"Grab a quick {MEETING_DURATION} here:\n"
            f"{BOOKING_LINK}\n\n"
            f"{MEETING_DAYS}, {MEETING_HOURS} works best.\n\n"
            f"Title: {MEETING_TITLE_TEMPLATE.format(company_name=company_name)}"
        ),
    }
