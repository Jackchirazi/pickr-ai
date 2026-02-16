"""
Pickr AI - Objection Handler (v2)
Spec steps 68-71: Fetch approved template from objections_kb.
AI cannot invent rebuttals. Every response ends with calendar link.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from pickr.models import ObjectionsKB
from pickr.config import BOOKING_LINK

logger = logging.getLogger(__name__)


class ObjectionHandler:
    """
    Handles objections using ONLY approved templates from objections_kb.
    AI fallback is only for unmatched types — and even then, short + calendar.
    """

    def handle(
        self,
        db: Session,
        objection_type: Optional[str],
        company_name: str,
        brand_names: list[str] = None,
    ) -> dict:
        """
        Fetch approved response template.
        Returns {subject, body, template_id, action}.
        """
        brand_names = brand_names or []

        # Step 68: Query objections_kb
        template = None
        if objection_type:
            template = db.query(ObjectionsKB).filter(
                ObjectionsKB.objection_type == objection_type,
                ObjectionsKB.is_active == True,
            ).first()

        if template:
            # Render template with variables
            body = template.template_body.format(
                company_name=company_name,
                brand_names=", ".join(brand_names[:3]) if brand_names else "relevant lines",
                booking_link=BOOKING_LINK,
            )
            subject = (template.template_subject or f"Re: {company_name}").format(
                company_name=company_name,
            )

            # Ensure calendar link is always at the end
            if BOOKING_LINK not in body:
                body += f"\n\n{BOOKING_LINK}"

            return {
                "subject": subject,
                "body": body,
                "template_id": template.objection_type,
                "action": "respond_then_calendar",
            }

        # Fallback: generic short response + calendar
        logger.info(f"No template for objection type: {objection_type}. Using generic.")
        return {
            "subject": f"Re: {company_name}",
            "body": (
                f"Totally understand.\n\n"
                f"Happy to share a few relevant lines that might fit — "
                f"best way is a quick call so I can understand your needs.\n\n"
                f"{BOOKING_LINK}"
            ),
            "template_id": None,
            "action": "respond_then_calendar",
        }
