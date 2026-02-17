"""
Pickr AI - Web Dashboard & API (v2)
FastAPI app with dashboard, webhook endpoints, and full CRUD.
"""
import csv
import io
import logging
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from pickr.models import (
    Lead, EmailJob, Reply, AuditLog, Job, Brand, SuppressionList,
    LeadCreateRequest, SessionLocal, init_db, get_db,
    LeadStatus, EmailJobStatus, JobStatus,
)
from pickr.pipeline import PickrPipeline
from pickr.suppression import suppress
from pickr.config import WEBHOOK_SECRET, EMAIL_PROVIDER, SCHEMA_VERSION

logger = logging.getLogger(__name__)

app = FastAPI(title="Pickr AI", version="2.0.0")
pipeline = PickrPipeline()


@app.on_event("startup")
def startup():
    pipeline.initialize()
    logger.info("Pickr AI v2 started. Schema: %s", SCHEMA_VERSION)


# ── Health ───────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "healthy", "schema_version": SCHEMA_VERSION, "provider": EMAIL_PROVIDER}


# ── Dashboard ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    stats = pipeline.get_stats(db)
    leads = db.query(Lead).order_by(Lead.created_at.desc()).limit(50).all()
    recent_emails = db.query(EmailJob).filter(EmailJob.status != EmailJobStatus.QUEUED.value).order_by(EmailJob.created_at.desc()).limit(20).all()
    recent_replies = db.query(Reply).order_by(Reply.created_at.desc()).limit(20).all()
    pending_approval = db.query(Reply).filter(Reply.draft_approved.is_(None), Reply.draft_response.isnot(None)).count()

    leads_html = ""
    for l in leads:
        status_class = {"qualified": "green", "disqualified": "red", "contacted": "blue",
                        "interested": "lime", "booked": "gold", "dead": "gray"}.get(l.status, "white")
        leads_html += f"""<tr>
            <td>{l.company_name}</td><td>{l.contact_email}</td><td>{l.channel or '-'}</td>
            <td><span style='color:{status_class}'>{l.status}</span></td>
            <td>{l.niche or '-'}</td><td>{str(l.created_at)[:16]}</td>
            <td><a href='/api/leads/{l.lead_id}'>view</a></td></tr>"""

    emails_html = ""
    for e in recent_emails:
        emails_html += f"<tr><td>{e.lead_id[:8]}...</td><td>T{e.touch_number or '-'}</td><td>{e.status}</td><td>{e.subject or '-'}</td><td>{str(e.created_at)[:16]}</td></tr>"

    replies_html = ""
    for r in recent_replies:
        approval = "pending" if r.draft_approved is None else ("approved" if r.draft_approved else "rejected")
        replies_html += f"<tr><td>{r.lead_id[:8]}...</td><td>{r.classification or '-'}</td><td>{r.action or '-'}</td><td>{approval}</td><td>{str(r.created_at)[:16]}</td></tr>"

    return f"""<!DOCTYPE html><html><head><title>Pickr AI v2</title>
<style>
body{{font-family:system-ui;background:#0a0a0a;color:#e0e0e0;margin:0;padding:20px}}
h1{{color:#fff}}.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:20px 0}}
.stat{{background:#1a1a2e;padding:16px;border-radius:8px;text-align:center}}
.stat .num{{font-size:28px;font-weight:bold;color:#00d4ff}}.stat .label{{font-size:12px;color:#888;margin-top:4px}}
table{{width:100%;border-collapse:collapse;margin:16px 0}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #222}}
th{{color:#888;font-size:12px;text-transform:uppercase}}
a{{color:#00d4ff;text-decoration:none}}
.section{{background:#111;border-radius:8px;padding:16px;margin:16px 0}}
.badge{{background:#ff4444;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px}}
</style></head><body>
<h1>Pickr AI v2 Dashboard</h1>
<div class='stats'>
<div class='stat'><div class='num'>{stats['total_leads']}</div><div class='label'>Total Leads</div></div>
<div class='stat'><div class='num'>{stats['qualified']}</div><div class='label'>Qualified</div></div>
<div class='stat'><div class='num'>{stats['contacted']}</div><div class='label'>Contacted</div></div>
<div class='stat'><div class='num'>{stats['interested']}</div><div class='label'>Interested</div></div>
<div class='stat'><div class='num'>{stats['booked']}</div><div class='label'>Booked</div></div>
<div class='stat'><div class='num'>{stats['total_emails']}</div><div class='label'>Emails Sent</div></div>
<div class='stat'><div class='num'>{stats['total_replies']}</div><div class='label'>Replies</div></div>
<div class='stat'><div class='num'>{stats['conversion_rate']}%</div><div class='label'>Conversion</div></div>
</div>
{f"<div class='badge'>Pending approvals: {pending_approval}</div>" if pending_approval else ""}
<div class='section'><h2>Leads</h2>
<table><tr><th>Company</th><th>Email</th><th>Channel</th><th>Status</th><th>Niche</th><th>Created</th><th>Detail</th></tr>{leads_html}</table></div>
<div class='section'><h2>Recent Emails</h2>
<table><tr><th>Lead</th><th>Touch</th><th>Status</th><th>Subject</th><th>Created</th></tr>{emails_html}</table></div>
<div class='section'><h2>Recent Replies</h2>
<table><tr><th>Lead</th><th>Classification</th><th>Action</th><th>Approval</th><th>Time</th></tr>{replies_html}</table></div>
</body></html>"""


# ── API: Leads ───────────────────────────────────────────────────

@app.post("/api/leads")
def create_lead(req: LeadCreateRequest, db: Session = Depends(get_db)):
    result = pipeline.create_lead(db, req)
    return result


@app.get("/api/leads")
def list_leads(status: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Lead)
    if status:
        q = q.filter(Lead.status == status)
    leads = q.order_by(Lead.created_at.desc()).limit(limit).all()
    return [{"lead_id": l.lead_id, "company_name": l.company_name, "email": l.contact_email,
             "status": l.status, "channel": l.channel, "niche": l.niche} for l in leads]


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: str, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return {
        "lead_id": lead.lead_id, "company_name": lead.company_name,
        "email": lead.contact_email, "website": lead.website_url,
        "status": lead.status, "channel": lead.channel, "niche": lead.niche,
        "disqualify_reason": lead.disqualify_reason,
        "signals": {
            "platform": lead.signals.detected_platform if lead.signals else None,
            "brands": lead.signals.brand_list if lead.signals else [],
            "scale_score": lead.signals.scale_score if lead.signals else None,
            "sku_count": lead.signals.sku_count_estimate if lead.signals else None,
        } if lead.signals else None,
        "leverage": {
            "primary_angle": lead.leverage.primary_angle if lead.leverage else None,
            "brands": lead.leverage.recommended_brands if lead.leverage else [],
        } if lead.leverage else None,
        "emails": [{"touch": e.touch_number, "status": e.status, "subject": e.subject}
                   for e in lead.email_jobs],
        "replies": [{"classification": r.classification, "action": r.action,
                     "text": r.raw_text[:100] if r.raw_text else None,
                     "approved": r.draft_approved}
                    for r in lead.replies],
    }


@app.post("/api/leads/csv")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    results = {"created": 0, "skipped": 0, "errors": 0}
    for row in reader:
        try:
            req = LeadCreateRequest(
                company_name=row.get("company_name", row.get("company", "")),
                website_url=row.get("website_url", row.get("website", "")),
                contact_email=row.get("contact_email", row.get("email", "")),
                store_count=row.get("store_count"),
                hq_location=row.get("hq", row.get("hq_location")),
                focus=row.get("focus"),
                channel=row.get("channel"),
                niche=row.get("niche"),
                location=row.get("location", row.get("locations")),
            )
            result = pipeline.create_lead(db, req)
            if result.get("suppressed") or result.get("dedupe"):
                results["skipped"] += 1
            else:
                results["created"] += 1
        except Exception as e:
            logger.error(f"CSV import error: {e}")
            results["errors"] += 1
    return results


@app.post("/api/leads/import-sheet")
def import_sheet(leads_data: list[dict], db: Session = Depends(get_db)):
    """
    Import leads from Google Sheet JSON array.
    Expected format: [
      {
        "company_name": "...",
        "website_url": "...",
        "store_count": "15+",
        "locations": "...",
        "hq": "...",
        "focus": "...",
        "channel": "retail",
        "niche": "beauty"
      }
    ]
    """
    results = {"created": 0, "skipped": 0, "errors": 0}
    for row in leads_data:
        try:
            # Generate a contact email placeholder - will be enriched
            company_name = row.get("company_name", "")
            website_url = row.get("website_url", "") or None  # None avoids unique constraint on empty

            # Generate a temporary email based on domain
            if website_url:
                domain = website_url.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
                if not domain:
                    domain = f"{company_name.lower().replace(' ', '')}.com"
                contact_email = f"info@{domain}"
            else:
                # Clean company name for email domain
                import unicodedata, re
                clean_name = unicodedata.normalize('NFKD', company_name.lower())
                clean_name = clean_name.encode('ascii', 'ignore').decode('ascii')
                clean_name = re.sub(r'[^a-z0-9]', '', clean_name)
                if not clean_name:
                    clean_name = "unknown"
                contact_email = f"info@{clean_name}.com"

            req = LeadCreateRequest(
                company_name=company_name,
                website_url=website_url,
                contact_email=contact_email,
                store_count=row.get("store_count"),
                hq_location=row.get("hq"),
                focus=row.get("focus"),
                channel=row.get("channel"),
                niche=row.get("niche"),
                location=row.get("locations"),
            )
            result = pipeline.create_lead(db, req)
            if result.get("suppressed") or result.get("dedupe"):
                results["skipped"] += 1
            else:
                results["created"] += 1
        except Exception as e:
            logger.error(f"Sheet import error: {e}")
            results["errors"] += 1
    return results


# ── API: Email Enrichment ───────────────────────────────────────

@app.post("/api/leads/{lead_id}/find-email")
def find_email_for_lead_endpoint(lead_id: str, db: Session = Depends(get_db)):
    """Find and enrich email for a specific lead."""
    result = pipeline.enrich_lead_email(db, lead_id)
    return result


@app.post("/api/leads/enrich-all")
def enrich_all_leads(db: Session = Depends(get_db)):
    """Find and enrich emails for all leads missing purchasing emails."""
    result = pipeline.enrich_all_leads_email(db)
    return result


@app.post("/api/db/migrate")
def run_migrations(db: Session = Depends(get_db)):
    """Add missing columns to leads table (safe to run multiple times)."""
    migrations = [
        ("purchasing_email", "ALTER TABLE leads ADD COLUMN IF NOT EXISTS purchasing_email VARCHAR(300)"),
        ("store_count", "ALTER TABLE leads ADD COLUMN IF NOT EXISTS store_count VARCHAR(50)"),
        ("hq_location", "ALTER TABLE leads ADD COLUMN IF NOT EXISTS hq_location VARCHAR(300)"),
        ("focus", "ALTER TABLE leads ADD COLUMN IF NOT EXISTS focus VARCHAR(500)"),
    ]
    results = []
    for name, sql in migrations:
        try:
            db.execute(text(sql))
            db.commit()
            results.append({"column": name, "status": "ok"})
        except Exception as e:
            db.rollback()
            results.append({"column": name, "status": "error", "detail": str(e)})
    return {"migrations": results}


# ── API: Pipeline Actions ────────────────────────────────────────

@app.post("/api/pipeline/process")
def process_jobs(db: Session = Depends(get_db)):
    return pipeline.process_queued_jobs(db)


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    return pipeline.get_stats(db)


# ── API: Replies + Approvals ─────────────────────────────────────

@app.post("/api/reply")
def handle_reply(lead_id: str, raw_text: str, db: Session = Depends(get_db)):
    return pipeline.handle_reply(db, lead_id, raw_text)


@app.get("/api/replies/pending")
def pending_replies(db: Session = Depends(get_db)):
    replies = db.query(Reply).filter(
        Reply.draft_approved.is_(None), Reply.draft_response.isnot(None)
    ).order_by(Reply.created_at.desc()).all()
    return [{"reply_id": r.reply_id, "lead_id": r.lead_id,
             "classification": r.classification, "objection_type": r.objection_type,
             "raw_text": r.raw_text[:200] if r.raw_text else None,
             "draft_response": r.draft_response}
            for r in replies]


@app.post("/api/replies/{reply_id}/approve")
def approve_reply(reply_id: str, db: Session = Depends(get_db)):
    reply = db.query(Reply).filter(Reply.reply_id == reply_id).first()
    if not reply:
        raise HTTPException(404, "Reply not found")
    reply.draft_approved = True
    db.commit()
    return {"status": "approved"}


@app.post("/api/replies/{reply_id}/reject")
def reject_reply(reply_id: str, db: Session = Depends(get_db)):
    reply = db.query(Reply).filter(Reply.reply_id == reply_id).first()
    if not reply:
        raise HTTPException(404, "Reply not found")
    reply.draft_approved = False
    db.commit()
    return {"status": "rejected"}


# ── API: Webhooks (SmartLead / Instantly) ────────────────────────

@app.post("/webhooks/provider")
async def provider_webhook(request: Request, db: Session = Depends(get_db)):
    """Process delivery/reply webhooks from SmartLead or Instantly."""
    payload = await request.json()

    # Import here to avoid circular
    from pickr.integrations.provider_adapter import get_provider
    adapter = get_provider()
    event = adapter.parse_webhook(payload)

    if event["event"] == "replied":
        email = event.get("email", "")
        lead = db.query(Lead).filter(Lead.contact_email == email).first()
        if lead:
            pipeline.handle_reply(db, lead.lead_id, event.get("reply_text", ""),
                                  provider_message_id=payload.get("message_id"))

    elif event["event"] == "bounced":
        email = event.get("email", "")
        suppress(db, email, reason="bounce")

    elif event["event"] == "unsubscribed":
        email = event.get("email", "")
        suppress(db, email, reason="unsubscribe")

    return {"received": True}


# ── API: Suppression ─────────────────────────────────────────────

@app.post("/api/suppress")
def suppress_email(email: str, reason: str = "manual", db: Session = Depends(get_db)):
    suppress(db, email, reason=reason)
    return {"suppressed": email}


# ── API: Audit ───────────────────────────────────────────────────

@app.get("/api/audit")
def audit_log(lead_id: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    if lead_id:
        q = q.filter(AuditLog.lead_id == lead_id)
    logs = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"event": l.event, "lead_id": l.lead_id, "actor": l.actor,
             "request_id": l.request_id, "payload": l.payload,
             "created_at": str(l.created_at)} for l in logs]


# ── API: Outcome (Step 81) ──────────────────────────────────────

@app.post("/api/leads/{lead_id}/outcome")
def set_outcome(lead_id: str, outcome: str, notes: Optional[str] = None, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.outcome = outcome
    lead.outcome_notes = notes
    if outcome == "deal_in_progress":
        lead.status = "booked"
    db.commit()
    return {"lead_id": lead_id, "outcome": outcome}


@app.post("/api/leads/{lead_id}/book")
def mark_booked(lead_id: str, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    from datetime import datetime
    lead.status = LeadStatus.BOOKED.value
    lead.booked_at = datetime.utcnow()
    db.commit()
    return {"lead_id": lead_id, "status": "booked"}
