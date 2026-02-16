"""
Pickr AI - Deterministic Leverage Rule Engine (v2)
Spec: AI cannot invent strategy. Strategy comes ONLY from the
rules_leverage_matrix stored in DB. Evaluated deterministic,
first-match by priority (lower priority number = higher rank).
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from pickr.models import (
    RulesLeverageMatrix, LeadSignal, Lead, LeadLeverage,
    Brand, LeverageAngle
)
from pickr.audit import audit
from pickr.config import MAX_BRANDS_PER_EMAIL

logger = logging.getLogger(__name__)


class LeverageEngine:
    """
    Deterministic rule engine for leverage selection.
    Loads rules from rules_leverage_matrix table, evaluates in priority order.
    """

    def evaluate(
        self,
        db: Session,
        lead: Lead,
        signals: LeadSignal,
        request_id: Optional[str] = None,
    ) -> Optional[LeadLeverage]:
        """
        Evaluate leverage rules for a lead. First match wins.

        Steps (from spec):
          43. Load leverage matrix where is_active=True ordered by priority ASC
          44. Evaluate each rule against lead fields — first match stops
          45. Write primary_angle, secondary_angle, brand_query
        """
        rules = db.query(RulesLeverageMatrix).filter(
            RulesLeverageMatrix.is_active == True
        ).order_by(RulesLeverageMatrix.priority.asc()).all()

        if not rules:
            logger.warning("No active leverage rules found in DB. Using growth fallback.")
            return self._create_leverage(
                db, lead,
                primary_angle="growth",
                secondary_angle=None,
                rule_id=None,
                match_reason="no_rules_loaded_fallback",
                brand_query={"priority_first": True, "cap": MAX_BRANDS_PER_EMAIL},
                request_id=request_id,
            )

        logger.info(f"Evaluating {len(rules)} leverage rules for lead {lead.lead_id}")

        for rule in rules:
            if self._rule_matches(rule, lead, signals):
                logger.info(
                    f"Rule matched: {rule.rule_id} (priority={rule.priority}) "
                    f"→ {rule.primary_angle} for lead {lead.lead_id}"
                )

                leverage = self._create_leverage(
                    db, lead,
                    primary_angle=rule.primary_angle,
                    secondary_angle=rule.secondary_angle,
                    rule_id=rule.rule_id,
                    match_reason=rule.description or f"rule_{rule.priority}_matched",
                    brand_query=rule.brand_query or {"priority_first": True, "cap": MAX_BRANDS_PER_EMAIL},
                    request_id=request_id,
                )

                # Audit
                audit(
                    db, "leverage_assigned",
                    lead_id=lead.lead_id,
                    actor="worker",
                    request_id=request_id,
                    payload={
                        "rule_id": rule.rule_id,
                        "primary_angle": rule.primary_angle,
                        "secondary_angle": rule.secondary_angle,
                    },
                )

                return leverage

        # No rule matched — growth fallback
        logger.info(f"No rule matched for lead {lead.lead_id}. Fallback: growth.")
        return self._create_leverage(
            db, lead,
            primary_angle="growth",
            secondary_angle=None,
            rule_id=None,
            match_reason="no_rule_matched_fallback",
            brand_query={"priority_first": True, "cap": MAX_BRANDS_PER_EMAIL},
            request_id=request_id,
        )

    def _rule_matches(
        self,
        rule: RulesLeverageMatrix,
        lead: Lead,
        signals: LeadSignal,
    ) -> bool:
        """Check if ALL non-null conditions in a rule match the lead."""

        # Channel match
        if rule.channel_match is not None:
            if (lead.channel or "").lower() != rule.channel_match.lower():
                return False

        # Min scale score
        if rule.min_scale_score is not None:
            if (signals.scale_score or 0) < rule.min_scale_score:
                return False

        # Max private label ratio
        if rule.max_private_label_ratio is not None:
            if (signals.private_label_ratio or 0) > rule.max_private_label_ratio:
                return False

        # Min MAP behavior score
        if rule.min_map_behavior_score is not None:
            if (signals.map_behavior_score or 0) < rule.min_map_behavior_score:
                return False

        # Min store count
        if rule.min_store_count is not None:
            if (signals.store_count or 0) < rule.min_store_count:
                return False

        # Requires brand overlap
        if rule.requires_brand_overlap:
            brand_list = signals.brand_list or []
            our_brands = db_brand_names = []  # Will be checked in pipeline context
            if not brand_list:
                return False

        # Requires adjacent brands
        if rule.requires_adjacent_brands:
            brand_list = signals.brand_list or []
            if not brand_list:
                return False

        return True

    def _create_leverage(
        self,
        db: Session,
        lead: Lead,
        primary_angle: str,
        secondary_angle: Optional[str],
        rule_id: Optional[str],
        match_reason: str,
        brand_query: dict,
        request_id: Optional[str] = None,
    ) -> LeadLeverage:
        """Create or update LeadLeverage record."""
        existing = db.query(LeadLeverage).filter(
            LeadLeverage.lead_id == lead.lead_id
        ).first()

        if existing:
            existing.primary_angle = primary_angle
            existing.secondary_angle = secondary_angle
            existing.matched_rule_id = rule_id
            existing.match_reason = match_reason
            existing.brand_query = brand_query
            return existing
        else:
            leverage = LeadLeverage(
                lead_id=lead.lead_id,
                primary_angle=primary_angle,
                secondary_angle=secondary_angle,
                matched_rule_id=rule_id,
                match_reason=match_reason,
                brand_query=brand_query,
            )
            db.add(leverage)
            return leverage

    def qualify(
        self,
        signals: LeadSignal,
    ) -> dict:
        """
        Determine if a lead qualifies. Spec disqualify gates:
          - private_label_only (ratio > 0.95)
          - arbitrage_no_scale (low SKU + low scale_score)
        """
        # Gate: Private label only
        if (signals.private_label_ratio or 0) > 0.95:
            return {
                "qualified": False,
                "reason": "private_label_only",
            }

        # Gate: Arbitrage with no scale
        if (signals.sku_count_estimate or 0) < 10 and (signals.scale_score or 0) < 20:
            return {
                "qualified": False,
                "reason": "arbitrage_no_scale",
            }

        return {
            "qualified": True,
            "reason": None,
        }


class BrandMatcher:
    """
    Brand matching engine.
    Spec: Hard cap at 3 brands. Priority brands first.
    Category adjacency fallback if too few candidates.
    """

    def match(
        self,
        db: Session,
        lead: Lead,
        signals: LeadSignal,
        brand_query: dict,
        request_id: Optional[str] = None,
    ) -> list[str]:
        """
        Select up to MAX_BRANDS_PER_EMAIL brands for a lead.

        Steps (from spec):
          47. Build SQL query from brand_query
          48. Fetch candidates: priority=True, category overlap, sort by pct_off desc
          49. Adjacency fallback if too few
          50. Pick top 1-3 with diversity rule
          51. Store recommended_brands
        """
        cap = brand_query.get("cap", MAX_BRANDS_PER_EMAIL)
        channel = lead.channel or "other"
        categories = signals.categories or []

        # Step 48: Fetch priority brands with channel fit
        query = db.query(Brand).filter(
            Brand.active == True,
            Brand.priority == True,
        )

        candidates = query.order_by(Brand.pct_off_retail.desc()).all()

        # Score and filter candidates
        scored = []
        for brand in candidates:
            score = 0
            brand_cats = brand.category or []
            brand_channels = brand.channel_fit or []

            # Channel fit
            if channel in brand_channels or "multi-channel" in brand_channels:
                score += 20

            # Category overlap
            cat_overlap = set(c.lower() for c in categories) & set(c.lower() for c in brand_cats)
            score += len(cat_overlap) * 15

            # High discount bonus
            if (brand.pct_off_retail or 0) >= 60:
                score += 10

            # Replenishable bonus (especially for Amazon)
            if brand.replenishable and channel == "amazon":
                score += 10

            scored.append({"brand": brand, "score": score})

        # Sort by score desc, pct_off_retail desc as tiebreaker
        scored.sort(key=lambda x: (x["score"], x["brand"].pct_off_retail or 0), reverse=True)

        # Step 49: Adjacency fallback — if fewer than cap, include non-priority
        if len(scored) < cap:
            non_priority = db.query(Brand).filter(
                Brand.active == True,
                Brand.priority == False,
            ).order_by(Brand.pct_off_retail.desc()).limit(cap).all()

            for brand in non_priority:
                if not any(s["brand"].brand_id == brand.brand_id for s in scored):
                    scored.append({"brand": brand, "score": 0})

        # Step 50: Diversity rule — avoid 3 same subcategory
        selected = []
        category_counts = {}
        for item in scored:
            if len(selected) >= cap:
                break
            brand = item["brand"]
            primary_cat = (brand.category or ["general"])[0]
            count = category_counts.get(primary_cat, 0)
            if count < 2:  # Max 2 from same category
                selected.append(brand.brand_id)
                category_counts[primary_cat] = count + 1

        # Audit
        if request_id:
            audit(
                db, "brand_matched",
                lead_id=lead.lead_id,
                actor="worker",
                request_id=request_id,
                payload={
                    "selected_brand_ids": selected,
                    "candidates_found": len(scored),
                    "cap": cap,
                },
            )

        return selected
