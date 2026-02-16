"""
Pickr AI - Audit Logging
Forensic traceability for every state change.
Spec: Every event writes to audit_log with request_id, actor, and payload.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from pickr.models import AuditLog

logger = logging.getLogger(__name__)


def gen_request_id() -> str:
    """Generate a unique request ID for tracing across services."""
    return f"req-{uuid.uuid4().hex[:12]}"


def audit(
    db: Session,
    event: str,
    lead_id: Optional[str] = None,
    job_id: Optional[str] = None,
    actor: str = "system",
    request_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> AuditLog:
    """
    Write an audit log entry.

    Events follow this convention:
      lead_created, lead_suppressed, lead_classified, lead_qualified,
      lead_disqualified, leverage_assigned, brand_matched,
      scrape_requested, scrape_completed, scrape_failed,
      email_rendered, email_sent, email_delivered, email_bounced,
      reply_received, reply_classified, reply_response_sent,
      suppression_added, job_created, job_started, job_completed, job_failed
    """
    entry = AuditLog(
        request_id=request_id or gen_request_id(),
        event=event,
        lead_id=lead_id,
        job_id=job_id,
        actor=actor,
        payload=payload or {},
    )
    db.add(entry)
    # Don't commit here — let the caller control the transaction
    logger.debug(f"AUDIT [{event}] lead={lead_id} job={job_id} actor={actor}")
    return entry


def audit_and_commit(
    db: Session,
    event: str,
    **kwargs,
) -> AuditLog:
    """Write audit entry and commit immediately."""
    entry = audit(db, event, **kwargs)
    db.commit()
    return entry
