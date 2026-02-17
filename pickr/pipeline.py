"""
Pickr AI - Pipeline Orchestrator (v2)
Full 82-step workflow aligned with Haim's spec.
Ties all modules together: intake → scrape → classify → leverage → brand → email → reply.
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from pickr.models import (
    Lead, LeadSignal, LeadQualification, LeadLeverage, Brand,
    EmailJob, Reply, Job, ScrapeJob, LeadStatus, JobStatus,
    EmailJobStatus, LeadCreateRequest, SessionLocal, init_db,
)
from pickr.enrichment.scraper import StorefrontScraper
from pickr.enrichment.analyzer import classify_lead, classify_reply
from pickr.enrichment.email_finder import find_email_for_lead
from pickr.engine.leverage import LeverageEngine, BrandMatcher
from pickr.engine.email_generator import generate_email, generate_interest_response
from pickr.engine.objection_handler import ObjectionHandler
from pickr.engine.linter import EmailLinter
from pickr.audit import audit, gen_request_id
from pickr.suppression import is_suppressed, suppress, check_remove_me
from pickr.config import (
    FOLLOWUP_TIMING, SCHEMA_VERSION, HUMAN_APPROVAL_THRESHOLD,
)

logger = logging.getLogger(__name__)


class PickrPipeline:
    """Main orchestrator for the Pickr AI sales pipeline."""

    def __init__(self):
        self.scraper = StorefrontScraper()
        self.leverage_engine = LeverageEngine()
        self.brand_matcher = BrandMatcher()
        self.objection_handler = ObjectionHandler()
        self.linter = EmailLinter()

    def initialize(self):
        """Initialize database tables."""
        init_db()
        logger.info("Pickr Pipeline initialized. Schema version: %s", SCHEMA_VERSION)

    # ── Step 1-12: Lead Intake ───────────────────────────────────

    def create_lead(self, db: Session, req: LeadCreateRequest, actor: str = "dashboard") -> dict:
        """Steps 2-12: Validate, suppress check, dedup, create lead, create job."""
        request_id = gen_request_id()
        email = req.contact_email.lower().strip()

        # Step 5: Suppression precheck
        if is_suppressed(db, email):
            return {"suppressed": True, "lead_id": None, "request_id": request_id}

        # Step 6: Dedup check on website_url
        if req.website_url:
            existing = db.query(Lead).filter(Lead.website_url == req.website_url).first()
            if existing:
                return {"suppressed": False, "lead_id": existing.lead_id, "dedupe": True, "request_id": request_id}

        # Step 7-8: Create lead
        lead = Lead(
            company_name=req.company_name, website_url=req.website_url,
            contact_email=email, channel=req.channel, niche=req.niche,
            location=req.location, notes=req.notes, status=LeadStatus.NEW.value,
            store_count=req.store_count, hq_location=req.hq_location, focus=req.focus,
        )
        db.add(lead)
        db.flush()

        # Step 9: Audit
        audit(db, "lead_created", lead_id=lead.lead_id, actor=actor,
              request_id=request_id, payload={"company_name": req.company_name, "email": email})

        # Step 10-11: Create research job and queue
        job = Job(job_type="lead_research", lead_id=lead.lead_id, status=JobStatus.QUEUED.value)
        db.add(job)
        db.commit()

        logger.info(f"Lead created: {lead.lead_id} ({lead.company_name}). Job: {job.job_id}")
        return {"suppressed": False, "lead_id": lead.lead_id, "job_id": job.job_id,
                "dedupe": False, "request_id": request_id}

    # ── Step 13-30: Research (Scrape) ────────────────────────────

    def research_lead(self, db: Session, lead: Lead, job: Job, request_id: Optional[str] = None) -> dict:
        """Steps 13-30: Scrape storefront, store signals."""
        request_id = request_id or gen_request_id()
        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        job.attempts += 1

        if is_suppressed(db, lead.contact_email):
            job.status = JobStatus.SUCCESS.value
            job.completed_at = datetime.utcnow()
            lead.status = LeadStatus.DISQUALIFIED.value
            lead.disqualify_reason = "suppressed"
            db.commit()
            return {"status": "suppressed"}

        scrape_job = ScrapeJob(lead_id=lead.lead_id, job_id=job.job_id)
        db.add(scrape_job)
        audit(db, "scrape_requested", lead_id=lead.lead_id, job_id=job.job_id,
              actor="worker", request_id=request_id)
        db.flush()

        scrape_result = {}
        if lead.website_url:
            scrape_result = self.scraper.scrape(lead.website_url, lead.lead_id)

        signals = LeadSignal(
            lead_id=lead.lead_id,
            detected_platform=scrape_result.get("detected_platform"),
            site_excerpt=scrape_result.get("site_excerpt"),
            categories=scrape_result.get("categories", []),
            sample_products=scrape_result.get("sample_products", []),
            brand_mentions_raw=scrape_result.get("brand_mentions_raw", []),
            sku_count_estimate=scrape_result.get("sku_count_estimate", 0),
            price_range_min=scrape_result.get("price_range_min"),
            price_range_max=scrape_result.get("price_range_max"),
            map_text_found=scrape_result.get("map_text_found", False),
            map_text_excerpt=scrape_result.get("map_text_excerpt"),
            private_label_ratio=scrape_result.get("private_label_ratio", 0.0),
            scrape_artifact_path=scrape_result.get("scrape_artifact_path"),
            scrape_artifact_hash=scrape_result.get("scrape_artifact_hash"),
        )
        db.add(signals)

        scrape_job.status = "success" if scrape_result.get("success") else "failed"
        scrape_job.pages_fetched = scrape_result.get("pages_fetched", 0)
        if scrape_result.get("error"):
            scrape_job.error = scrape_result["error"]

        audit(db, "scrape_completed", lead_id=lead.lead_id, job_id=job.job_id,
              actor="worker", request_id=request_id,
              payload={"pages_fetched": scrape_job.pages_fetched, "success": scrape_result.get("success")})
        db.commit()
        return {"status": "scraped", "signals": scrape_result}

    # ── Step 31-42: Classify + Qualify ───────────────────────────

    def classify_and_qualify(self, db: Session, lead: Lead, job: Job, request_id: Optional[str] = None) -> dict:
        """Steps 31-42: AI classify, validate, qualify/disqualify gate."""
        request_id = request_id or gen_request_id()
        signals = lead.signals
        if not signals:
            return {"status": "no_signals"}

        signals_dict = {
            "detected_platform": signals.detected_platform,
            "categories": signals.categories,
            "brand_mentions_raw": signals.brand_mentions_raw,
            "sku_count_estimate": signals.sku_count_estimate,
            "price_range_min": signals.price_range_min,
            "price_range_max": signals.price_range_max,
            "site_excerpt": signals.site_excerpt,
            "map_text_found": signals.map_text_found,
        }

        classifier_output, llm_call_id = classify_lead(signals_dict, lead.company_name, lead.niche)

        signals.brand_list = classifier_output.brand_list
        signals.price_tier = classifier_output.price_tier
        signals.scale_score = classifier_output.scale_score
        signals.map_behavior_score = classifier_output.map_behavior_score
        signals.store_count = classifier_output.store_count

        qual_result = self.leverage_engine.qualify(signals)
        qualification = LeadQualification(
            lead_id=lead.lead_id, qualifies=qual_result["qualified"],
            disqualify_reason=qual_result["reason"],
            llm_call_id=llm_call_id, schema_version=SCHEMA_VERSION,
        )
        db.add(qualification)

        if qual_result["qualified"]:
            lead.status = LeadStatus.RESEARCHED.value
        else:
            lead.status = LeadStatus.DISQUALIFIED.value
            lead.disqualify_reason = qual_result["reason"]

        audit(db, "lead_classified", lead_id=lead.lead_id, job_id=job.job_id,
              actor="worker", request_id=request_id,
              payload={"llm_call_id": llm_call_id, "qualifies": qual_result["qualified"]})
        db.commit()

        if not qual_result["qualified"]:
            job.status = JobStatus.SUCCESS.value
            job.completed_at = datetime.utcnow()
            db.commit()
            return {"status": "disqualified", "reason": qual_result["reason"]}
        return {"status": "qualified"}

    # ── Step 43-51: Leverage + Brand Match ───────────────────────

    def assign_leverage_and_brands(self, db: Session, lead: Lead, request_id: Optional[str] = None) -> dict:
        """Steps 43-51: Deterministic rule evaluation + brand matching."""
        request_id = request_id or gen_request_id()
        signals = lead.signals
        if not signals:
            return {"status": "no_signals"}

        leverage = self.leverage_engine.evaluate(db, lead, signals, request_id)
        brand_query = leverage.brand_query or {"priority_first": True, "cap": 3}
        brand_ids = self.brand_matcher.match(db, lead, signals, brand_query, request_id)
        leverage.recommended_brands = brand_ids
        lead.status = LeadStatus.QUALIFIED.value
        db.commit()

        logger.info(f"Leverage: {lead.company_name} → {leverage.primary_angle} | Brands: {brand_ids}")
        return {"status": "leveraged", "primary_angle": leverage.primary_angle, "brand_ids": brand_ids}

    # ── Step 52-62: Email Sequence ───────────────────────────────

    def create_email_sequence(self, db: Session, lead: Lead, request_id: Optional[str] = None) -> dict:
        """Steps 52-53: Create 5 email_jobs rows for the sequence."""
        request_id = request_id or gen_request_id()
        leverage = lead.leverage
        if not leverage:
            return {"status": "no_leverage"}

        sequence_id = f"seq-{uuid.uuid4().hex[:12]}"
        brand_names = []
        if leverage.recommended_brands:
            brands = db.query(Brand).filter(Brand.brand_id.in_(leverage.recommended_brands)).all()
            brand_names = [b.brand_name for b in brands]

        lint_result = self.linter.lint_template_inputs({"company_name": lead.company_name, "brand_names": brand_names})
        if not lint_result["ok"]:
            return {"status": "lint_failed", "violations": lint_result["violations"]}

        now = datetime.utcnow()
        for touch in range(1, 6):
            delay_hours = FOLLOWUP_TIMING.get(touch, 0)
            email_data = generate_email(
                company_name=lead.company_name, niche=lead.niche or "retail",
                primary_angle=leverage.primary_angle, touch_number=touch,
                brand_names=brand_names,
                site_excerpt=lead.signals.site_excerpt if lead.signals else None,
                categories=lead.signals.categories if lead.signals else None,
            )
            body_lint = self.linter.lint(email_data["subject"], email_data["body"], brand_count=len(brand_names))

            email_job = EmailJob(
                lead_id=lead.lead_id, sequence_id=sequence_id, touch_number=touch,
                email_type="sequence", subject=email_data["subject"], body=email_data["body"],
                status=EmailJobStatus.RENDERED.value if body_lint["ok"] else EmailJobStatus.FAILED.value,
                scheduled_at=now + timedelta(hours=delay_hours),
                error=str(body_lint["violations"]) if not body_lint["ok"] else None,
            )
            db.add(email_job)
            audit(db, "email_rendered", lead_id=lead.lead_id, actor="worker", request_id=request_id,
                  payload={"touch": touch, "sequence_id": sequence_id, "lint_ok": body_lint["ok"]})

        lead.status = LeadStatus.CONTACTED.value
        db.commit()
        logger.info(f"Email sequence: {sequence_id} for {lead.company_name}")
        return {"status": "sequence_created", "sequence_id": sequence_id}

    # ── Step 64-76: Reply Handling ───────────────────────────────

    def handle_reply(self, db: Session, lead_id: str, raw_text: str,
                     email_job_id: Optional[str] = None, provider_message_id: Optional[str] = None) -> dict:
        """Steps 64-76: Store reply, classify, route action."""
        request_id = gen_request_id()
        lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if not lead:
            return {"error": "Lead not found"}

        reply = Reply(lead_id=lead_id, email_job_id=email_job_id,
                      raw_text=raw_text, provider_message_id=provider_message_id)
        db.add(reply)
        db.flush()

        audit(db, "reply_received", lead_id=lead_id, actor="webhook", request_id=request_id,
              payload={"reply_id": reply.reply_id, "text_preview": raw_text[:100]})

        # Suppression check
        if check_remove_me(raw_text):
            suppress(db, lead.contact_email, reason="unsubscribe", source_lead_id=lead_id, request_id=request_id)
            reply.classification = "unsubscribe"
            reply.action = "suppress"
            lead.status = LeadStatus.DEAD.value
            db.commit()
            return {"action": "suppressed", "reply_id": reply.reply_id}

        # AI classify
        context = f"Company: {lead.company_name}, Niche: {lead.niche}, Angle: {lead.leverage.primary_angle if lead.leverage else 'unknown'}"
        classifier_output, llm_call_id = classify_reply(raw_text, context)

        reply.classification = classifier_output.classification
        reply.objection_type = classifier_output.objection_type
        reply.action = classifier_output.action
        reply.interest_level = classifier_output.interest_level
        reply.llm_call_id = llm_call_id

        audit(db, "reply_classified", lead_id=lead_id, actor="worker", request_id=request_id,
              payload={"classification": classifier_output.classification, "action": classifier_output.action})

        if classifier_output.classification == "interested":
            lead.status = LeadStatus.INTERESTED.value
            response = generate_interest_response(lead.company_name)
            reply.draft_response = response["body"]
            self._maybe_require_approval(db, reply)
        elif classifier_output.classification == "objection":
            lead.status = LeadStatus.OBJECTION.value
            brand_names = self._get_brand_names(db, lead)
            response = self.objection_handler.handle(db, classifier_output.objection_type, lead.company_name, brand_names)
            reply.draft_response = response["body"]
            self._maybe_require_approval(db, reply)
        elif classifier_output.classification == "not_interested":
            lead.status = LeadStatus.DEAD.value
        else:
            reply.action = "handoff_to_human"

        if classifier_output.classification in ("interested", "objection"):
            self._pause_pending_emails(db, lead_id)

        db.commit()
        return {"reply_id": reply.reply_id, "classification": classifier_output.classification,
                "action": reply.action, "draft_response": reply.draft_response,
                "needs_approval": reply.draft_approved is None and reply.draft_response is not None}

    # ── Full Pipeline Run ────────────────────────────────────────

    def process_lead_full(self, db: Session, lead: Lead, job: Job) -> dict:
        """Run complete pipeline for a single lead."""
        request_id = gen_request_id()
        results = {}
        res = self.research_lead(db, lead, job, request_id)
        results["research"] = res
        if res["status"] in ("suppressed",):
            return results

        db.refresh(lead)
        res = self.classify_and_qualify(db, lead, job, request_id)
        results["classification"] = res
        if res["status"] == "disqualified":
            return results

        db.refresh(lead)
        res = self.assign_leverage_and_brands(db, lead, request_id)
        results["leverage"] = res

        db.refresh(lead)
        res = self.create_email_sequence(db, lead, request_id)
        results["email_sequence"] = res

        job.status = JobStatus.SUCCESS.value
        job.completed_at = datetime.utcnow()
        db.commit()
        return results

    def process_queued_jobs(self, db: Session) -> dict:
        """Process all queued lead_research jobs."""
        jobs = db.query(Job).filter(Job.job_type == "lead_research", Job.status == JobStatus.QUEUED.value).all()
        results = {"processed": 0, "errors": 0}
        for job in jobs:
            lead = db.query(Lead).filter(Lead.lead_id == job.lead_id).first()
            if not lead:
                job.status = JobStatus.FAILED.value
                job.error = "Lead not found"
                results["errors"] += 1
                continue
            try:
                self.process_lead_full(db, lead, job)
                results["processed"] += 1
            except Exception as e:
                job.status = JobStatus.FAILED.value
                job.error = str(e)
                results["errors"] += 1
                logger.error(f"Job {job.job_id} failed: {e}")
        db.commit()
        return results

    def get_stats(self, db: Session) -> dict:
        """Pipeline statistics."""
        total = db.query(Lead).count()
        return {
            "total_leads": total,
            "new": db.query(Lead).filter(Lead.status == LeadStatus.NEW.value).count(),
            "researched": db.query(Lead).filter(Lead.status == LeadStatus.RESEARCHED.value).count(),
            "qualified": db.query(Lead).filter(Lead.status == LeadStatus.QUALIFIED.value).count(),
            "disqualified": db.query(Lead).filter(Lead.status == LeadStatus.DISQUALIFIED.value).count(),
            "contacted": db.query(Lead).filter(Lead.status == LeadStatus.CONTACTED.value).count(),
            "interested": db.query(Lead).filter(Lead.status == LeadStatus.INTERESTED.value).count(),
            "booked": db.query(Lead).filter(Lead.status == LeadStatus.BOOKED.value).count(),
            "dead": db.query(Lead).filter(Lead.status == LeadStatus.DEAD.value).count(),
            "total_emails": db.query(EmailJob).filter(EmailJob.status == EmailJobStatus.SENT.value).count(),
            "total_replies": db.query(Reply).count(),
            "conversion_rate": round(db.query(Lead).filter(Lead.status == LeadStatus.BOOKED.value).count() / max(total, 1) * 100, 1),
        }

    def _get_brand_names(self, db: Session, lead: Lead) -> list[str]:
        if not lead.leverage or not lead.leverage.recommended_brands:
            return []
        brands = db.query(Brand).filter(Brand.brand_id.in_(lead.leverage.recommended_brands)).all()
        return [b.brand_name for b in brands]

    def _pause_pending_emails(self, db: Session, lead_id: str):
        pending = db.query(EmailJob).filter(
            EmailJob.lead_id == lead_id,
            EmailJob.status.in_([EmailJobStatus.QUEUED.value, EmailJobStatus.RENDERED.value]),
        ).all()
        for ej in pending:
            ej.status = EmailJobStatus.PAUSED.value

    def _maybe_require_approval(self, db: Session, reply: Reply):
        total = db.query(Reply).filter(Reply.draft_response.isnot(None)).count()
        if total <= HUMAN_APPROVAL_THRESHOLD:
            reply.draft_approved = None
        else:
            reply.draft_approved = True

    # ── Email Enrichment ─────────────────────────────────────────────

    def enrich_lead_email(self, db: Session, lead_id: str) -> dict:
        """Find and enrich a lead's purchasing email."""
        lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if not lead:
            return {"error": "Lead not found"}

        if not lead.website_url:
            return {"error": "No website URL for lead", "lead_id": lead_id}

        # Skip if already has purchasing email
        if lead.purchasing_email:
            return {"status": "already_enriched", "email": lead.purchasing_email, "lead_id": lead_id}

        logger.info(f"Enriching email for lead {lead_id}: {lead.company_name}")
        email = find_email_for_lead(lead.company_name, lead.website_url)

        if email:
            lead.purchasing_email = email
            db.commit()
            logger.info(f"Enriched email for {lead.company_name}: {email}")
            return {"status": "enriched", "email": email, "lead_id": lead_id}

        return {"status": "not_found", "lead_id": lead_id}

    def enrich_all_leads_email(self, db: Session) -> dict:
        """Find and enrich emails for all leads missing purchasing emails."""
        leads = db.query(Lead).filter(
            Lead.website_url.isnot(None),
            Lead.purchasing_email.is_(None)
        ).all()

        results = {"enriched": 0, "failed": 0, "already_have": 0}

        for lead in leads:
            try:
                result = self.enrich_lead_email(db, lead.lead_id)
                if result.get("status") == "enriched":
                    results["enriched"] += 1
                elif result.get("status") == "already_enriched":
                    results["already_have"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Error enriching {lead.lead_id}: {e}")
                results["failed"] += 1

        return results
