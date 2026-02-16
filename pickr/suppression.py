"""
Pickr AI - Suppression List
Non-negotiable: unsubscribe/remove-me must suppress forever.
Checked at 3 gates: intake, before send, on reply classification.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from pickr.models import SuppressionList, Lead, EmailJob, EmailJobStatus
from pickr.audit import audit

logger = logging.getLogger(__name__)


def extract_domain(email: str) -> str:
    """Extract domain from an email address."""
    if "@" in email:
        return email.split("@")[1].lower().strip()
    return ""


def is_suppressed(db: Session, email: str) -> bool:
    """
    Check if an email or its domain is suppressed.
    Called at: lead intake, before email send, on reply classification.
    """
    email_lower = email.lower().strip()
    domain = extract_domain(email_lower)

    # Check exact email match
    email_match = db.query(SuppressionList).filter(
        SuppressionList.email == email_lower
    ).first()
    if email_match:
        logger.info(f"SUPPRESSED (email): {email_lower} — reason: {email_match.reason}")
        return True

    # Check domain match
    if domain:
        domain_match = db.query(SuppressionList).filter(
            SuppressionList.domain == domain,
            SuppressionList.email.is_(None),
        ).first()
        if domain_match:
            logger.info(f"SUPPRESSED (domain): {domain} — reason: {domain_match.reason}")
            return True

    return False


def suppress(
    db: Session,
    email: str,
    reason: str = "unsubscribe",
    source_lead_id: Optional[str] = None,
    suppress_domain: bool = True,
    request_id: Optional[str] = None,
) -> SuppressionList:
    """
    Add email (and optionally domain) to suppression list.
    Also pauses all pending email_jobs for this email.
    """
    email_lower = email.lower().strip()
    domain = extract_domain(email_lower)

    # Add email suppression
    existing = db.query(SuppressionList).filter(
        SuppressionList.email == email_lower
    ).first()

    if not existing:
        entry = SuppressionList(
            email=email_lower,
            domain=domain if suppress_domain else None,
            reason=reason,
            source_lead_id=source_lead_id,
        )
        db.add(entry)
        logger.info(f"SUPPRESSED: {email_lower} (reason: {reason})")

        # Audit
        audit(
            db, "suppression_added",
            lead_id=source_lead_id,
            actor="system",
            request_id=request_id,
            payload={
                "email": email_lower,
                "domain": domain,
                "reason": reason,
                "suppress_domain": suppress_domain,
            },
        )
    else:
        entry = existing
        logger.info(f"Already suppressed: {email_lower}")

    # Pause all pending email jobs for leads with this email
    leads = db.query(Lead).filter(Lead.contact_email == email_lower).all()
    for lead in leads:
        # Update lead status
        lead.status = "dead"
        lead.disqualify_reason = f"suppressed: {reason}"

        # Pause pending email jobs
        pending_jobs = db.query(EmailJob).filter(
            EmailJob.lead_id == lead.lead_id,
            EmailJob.status.in_([
                EmailJobStatus.QUEUED.value,
                EmailJobStatus.RENDERED.value,
            ]),
        ).all()
        for job in pending_jobs:
            job.status = EmailJobStatus.PAUSED.value
            logger.info(f"Paused email job {job.job_id} for suppressed lead")

    db.commit()
    return entry


def check_remove_me(text: str) -> bool:
    """Check if reply text contains unsubscribe/remove-me signals."""
    lower = text.lower()
    removal_phrases = [
        "unsubscribe",
        "remove me",
        "remove my",
        "stop emailing",
        "stop contacting",
        "opt out",
        "opt-out",
        "take me off",
        "don't email",
        "do not email",
        "do not contact",
        "don't contact",
        "no more emails",
        "stop sending",
        "not interested please remove",
        "please remove",
    ]
    return any(phrase in lower for phrase in removal_phrases)
