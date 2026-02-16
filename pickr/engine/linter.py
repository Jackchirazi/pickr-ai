"""
Pickr AI - Forbidden Phrase Linter
Spec: Every email subject+body must be scanned before send.
Blocks: cost basis, invoices, exclusivity, full catalog, margins, etc.
"""
import logging
from typing import Optional
from pickr.config import FORBIDDEN_PHRASES, MAX_BRANDS_PER_EMAIL

logger = logging.getLogger(__name__)


class EmailLinter:
    """
    Pre-send linter that enforces information control rules.
    No email leaves the system without passing this check.
    """

    def lint(
        self,
        subject: str,
        body: str,
        brand_count: int = 0,
    ) -> dict:
        """
        Lint an email for forbidden content.

        Returns:
            {
                "ok": bool,
                "violations": [{"phrase": str, "location": "subject"|"body"}],
                "brand_cap_violation": bool,
            }
        """
        violations = []

        # Check forbidden phrases
        for phrase in FORBIDDEN_PHRASES:
            phrase_lower = phrase.lower()
            if phrase_lower in subject.lower():
                violations.append({"phrase": phrase, "location": "subject"})
            if phrase_lower in body.lower():
                violations.append({"phrase": phrase, "location": "body"})

        # Check brand count cap
        brand_cap_violation = brand_count > MAX_BRANDS_PER_EMAIL

        if violations:
            logger.warning(
                f"LINT FAILED: {len(violations)} forbidden phrase(s) found: "
                f"{[v['phrase'] for v in violations]}"
            )

        if brand_cap_violation:
            logger.warning(
                f"LINT FAILED: Brand count {brand_count} exceeds cap of {MAX_BRANDS_PER_EMAIL}"
            )

        ok = len(violations) == 0 and not brand_cap_violation

        return {
            "ok": ok,
            "violations": violations,
            "brand_cap_violation": brand_cap_violation,
        }

    def lint_template_inputs(
        self,
        template_vars: dict,
    ) -> dict:
        """
        Spec step 54: Check no forbidden variables are present.
        No catalogs attached. No more than 3 brands.
        """
        violations = []

        # Check brand count in variables
        brands = template_vars.get("brand_names", [])
        if len(brands) > MAX_BRANDS_PER_EMAIL:
            violations.append({
                "issue": f"Too many brands: {len(brands)} (max {MAX_BRANDS_PER_EMAIL})",
                "field": "brand_names",
            })

        # Check for forbidden variable keys
        forbidden_vars = ["catalog_url", "full_catalog", "price_list", "invoice"]
        for var in forbidden_vars:
            if var in template_vars and template_vars[var]:
                violations.append({
                    "issue": f"Forbidden variable present: {var}",
                    "field": var,
                })

        ok = len(violations) == 0

        if not ok:
            logger.warning(f"TEMPLATE LINT FAILED: {violations}")

        return {
            "ok": ok,
            "violations": violations,
        }
