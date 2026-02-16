"""
Pickr AI - Data Models (v2)
Full schema aligned with Haim's 82-step spec.

Tables:
  leads, lead_signals, lead_qualification, lead_leverage,
  brands, email_jobs, replies, suppression_list,
  audit_log, jobs, scrape_jobs, rules_leverage_matrix, objections_kb, config
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float,
    Boolean, DateTime, ForeignKey, JSON, UniqueConstraint,
    Index, BigInteger, event
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from pydantic import BaseModel, Field
from pickr.config import DATABASE_URL

# ── SQLAlchemy Setup ──────────────────────────────────────────────

Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def gen_uuid():
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────

class LeadStatus(str, Enum):
    NEW = "new"
    RESEARCHED = "researched"       # After scrape + classify
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    CONTACTED = "contacted"         # Touch 1 sent
    REPLIED = "replied"
    OBJECTION = "objection"
    INTERESTED = "interested"
    BOOKED = "booked"
    DEAD = "dead"


class Channel(str, Enum):
    AMAZON = "amazon"
    WALMART = "walmart"
    RETAIL = "retail"
    MULTI = "multi-channel"
    SHOPIFY = "shopify"
    OTHER = "other"


class LeverageAngle(str, Enum):
    EXPANSION = "expansion"
    ALIGNMENT = "alignment"
    STABILITY = "stability"
    SCALABILITY = "scalability"
    INSTITUTIONAL = "institutional"
    GROWTH = "growth"


class JobType(str, Enum):
    LEAD_RESEARCH = "lead_research"
    SEND_EMAIL = "send_email"
    CLASSIFY_REPLY = "classify_reply"
    SCRAPE = "scrape"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class EmailJobStatus(str, Enum):
    QUEUED = "queued"
    RENDERED = "rendered"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    SPAM = "spam"
    PAUSED = "paused"
    FAILED = "failed"


class ReplyClassification(str, Enum):
    INTERESTED = "interested"
    OBJECTION = "objection"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    OUT_OF_OFFICE = "out_of_office"
    UNKNOWN = "unknown"


class DisqualifyReason(str, Enum):
    PRIVATE_LABEL_ONLY = "private_label_only"
    ARBITRAGE_NO_SCALE = "arbitrage_no_scale"
    REMOVE_ME = "remove_me"
    UNKNOWN = "unknown"


class Outcome(str, Enum):
    NOT_FIT = "not_fit"
    FOLLOW_UP = "follow_up"
    DEAL_IN_PROGRESS = "deal_in_progress"
    CLOSED = "closed"


# ── Database Models ───────────────────────────────────────────────

class Lead(Base):
    """Core lead record. Source of truth for lead state."""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(36), default=gen_uuid, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Input data
    company_name = Column(String(300), nullable=False)
    website_url = Column(String(500), unique=True)
    contact_email = Column(String(300), nullable=False)
    channel = Column(String(50))
    niche = Column(String(200))
    location = Column(String(300))
    notes = Column(Text)

    # Status
    status = Column(String(50), default=LeadStatus.NEW.value, index=True)
    disqualify_reason = Column(String(200))

    # Meeting tracking
    booked_at = Column(DateTime)
    outcome = Column(String(50))
    outcome_notes = Column(Text)

    # Relationships
    signals = relationship("LeadSignal", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    qualification = relationship("LeadQualification", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    leverage = relationship("LeadLeverage", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    email_jobs = relationship("EmailJob", back_populates="lead", cascade="all, delete-orphan")
    replies = relationship("Reply", back_populates="lead", cascade="all, delete-orphan")


class LeadSignal(Base):
    """Structured signals extracted from scraping + AI classification."""
    __tablename__ = "lead_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Scraper raw signals
    detected_platform = Column(String(50))          # shopify, bigcommerce, woocommerce, custom
    site_excerpt = Column(Text)                      # First 2k chars visible text
    categories = Column(JSON, default=list)          # ["Outdoor", "Camping"]
    sample_products = Column(JSON, default=list)     # [{title, price, vendor}]
    brand_mentions_raw = Column(JSON, default=list)  # Raw brand tokens from scraper
    sku_count_estimate = Column(Integer, default=0)
    price_range_min = Column(Float)
    price_range_max = Column(Float)
    map_text_found = Column(Boolean, default=False)
    map_text_excerpt = Column(Text)
    private_label_ratio = Column(Float, default=0.0)

    # AI-normalized signals
    brand_list = Column(JSON, default=list)          # Cleaned brand list from AI
    price_tier = Column(String(50))                  # luxury, mid, discount, mixed
    scale_score = Column(Integer, default=0)         # 0-100
    map_behavior_score = Column(Integer, default=0)  # 0-100
    store_count = Column(Integer, default=0)

    # Evidence pointers
    scrape_artifact_path = Column(String(500))       # Path to HTML snapshot
    scrape_artifact_hash = Column(String(64))        # SHA256 of snapshot

    lead = relationship("Lead", back_populates="signals")


class LeadQualification(Base):
    """Qualification decision for a lead."""
    __tablename__ = "lead_qualification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    qualifies = Column(Boolean, nullable=False)
    disqualify_reason = Column(String(200))
    llm_call_id = Column(String(36))                # Trace to the AI call
    schema_version = Column(String(50))

    lead = relationship("Lead", back_populates="qualification")


class LeadLeverage(Base):
    """Leverage strategy assigned to a qualified lead."""
    __tablename__ = "lead_leverage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    primary_angle = Column(String(50))
    secondary_angle = Column(String(50))
    matched_rule_id = Column(String(36))             # Which rule matched
    match_reason = Column(Text)
    brand_query = Column(JSON)                       # Filter used for brand selection
    recommended_brands = Column(JSON, default=list)  # [brand_id, brand_id, brand_id] max 3

    lead = relationship("Lead", back_populates="leverage")


class Brand(Base):
    """Curated brand catalog."""
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_id = Column(String(36), default=gen_uuid, unique=True, nullable=False)
    brand_name = Column(String(300), nullable=False, unique=True)
    category = Column(JSON, default=list)            # ["outdoor", "apparel"]
    pct_off_retail = Column(Float)                   # e.g., 65.0
    mov = Column(Float)                              # Minimum order value
    lead_time_min = Column(Integer)                  # Days
    lead_time_max = Column(Integer)                  # Days
    origin = Column(String(100))
    channel_fit = Column(JSON, default=list)         # ["retail", "amazon", "multi-channel"]
    replenishable = Column(Boolean, default=False)
    priority = Column(Boolean, default=False)        # Computed: pct_off_retail >= 45
    catalog_url = Column(String(500))                # Link to curated sheet
    notes = Column(Text)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailJob(Base):
    """Every outbound email tracked as a job. Traceable to lead + sequence."""
    __tablename__ = "email_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), default=gen_uuid, unique=True, nullable=False, index=True)
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), nullable=False, index=True)
    sequence_id = Column(String(36), index=True)     # Groups all 5 touches
    created_at = Column(DateTime, default=datetime.utcnow)

    # Email content
    touch_number = Column(Integer)                   # 1-5 for sequence, null for replies
    email_type = Column(String(50), default="sequence")  # sequence, reply, calendar
    subject = Column(String(500))
    body = Column(Text)

    # Status
    status = Column(String(50), default=EmailJobStatus.QUEUED.value, index=True)
    scheduled_at = Column(DateTime)
    sent_at = Column(DateTime)
    error = Column(Text)

    # Provider tracking
    provider = Column(String(50))                    # smartlead, instantly
    provider_campaign_id = Column(String(200))
    provider_lead_id = Column(String(200))
    provider_message_id = Column(String(200))

    # Reply linkage
    reply_id = Column(String(36))                    # If this is a response to a reply

    lead = relationship("Lead", back_populates="email_jobs")


class Reply(Base):
    """Inbound reply from a lead."""
    __tablename__ = "replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reply_id = Column(String(36), default=gen_uuid, unique=True, nullable=False, index=True)
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), nullable=False, index=True)
    email_job_id = Column(String(36), index=True)    # Which email they replied to
    created_at = Column(DateTime, default=datetime.utcnow)

    # Raw content
    raw_text = Column(Text)
    provider_message_id = Column(String(200))

    # Classification (AI strict JSON)
    classification = Column(String(50))              # interested, objection, not_interested, unsubscribe
    objection_type = Column(String(100))             # catalog_request, pricing, margins, etc.
    action = Column(String(50))                      # send_calendar, send_curated_catalog, suppress, handoff_to_human
    interest_level = Column(Integer)                 # 1-10

    # Draft response
    draft_response = Column(Text)
    draft_approved = Column(Boolean)                 # Human approval for first 200
    response_sent = Column(Boolean, default=False)

    # AI trace
    llm_call_id = Column(String(36))

    lead = relationship("Lead", back_populates="replies")


class SuppressionList(Base):
    """Permanent suppression. Checked at intake, before send, on reply."""
    __tablename__ = "suppression_list"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    email = Column(String(300), index=True)
    domain = Column(String(300), index=True)
    reason = Column(String(200))                     # unsubscribe, bounce, spam, manual
    source_lead_id = Column(String(36))

    __table_args__ = (
        UniqueConstraint("email", "domain", name="uq_suppression_email_domain"),
    )


class AuditLog(Base):
    """Forensic traceability for every state change."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    request_id = Column(String(36), index=True)      # Trace across services
    event = Column(String(100), nullable=False, index=True)
    lead_id = Column(String(36), index=True)
    job_id = Column(String(36))
    actor = Column(String(100))                      # dashboard, worker, webhook, system
    payload = Column(JSON)


class Job(Base):
    """Job queue record. Every automation tied to a job_id."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), default=gen_uuid, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job_type = Column(String(50), nullable=False)    # lead_research, send_email, etc.
    lead_id = Column(String(36), index=True)
    status = Column(String(50), default=JobStatus.QUEUED.value, index=True)
    attempts = Column(Integer, default=0)
    locked_by = Column(String(100))
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error = Column(Text)


class ScrapeJob(Base):
    """Scraping sub-job with artifact tracking."""
    __tablename__ = "scrape_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scrape_id = Column(String(36), default=gen_uuid, unique=True, nullable=False)
    lead_id = Column(String(36), index=True)
    job_id = Column(String(36), index=True)          # Parent job
    created_at = Column(DateTime, default=datetime.utcnow)

    status = Column(String(50), default="queued")
    pages_fetched = Column(Integer, default=0)
    budget_ms = Column(Integer, default=25000)
    max_pages = Column(Integer, default=6)
    error = Column(Text)


class RulesLeverageMatrix(Base):
    """Deterministic leverage rules. AI cannot invent strategy."""
    __tablename__ = "rules_leverage_matrix"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(36), default=gen_uuid, unique=True, nullable=False)
    priority = Column(Integer, nullable=False)        # Lower = higher priority
    is_active = Column(Boolean, default=True)

    # Match conditions (all optional; non-null fields must ALL match)
    channel_match = Column(String(50))               # If set, lead.channel must match
    min_scale_score = Column(Integer)
    max_private_label_ratio = Column(Float)
    min_map_behavior_score = Column(Integer)
    min_store_count = Column(Integer)
    requires_brand_overlap = Column(Boolean)          # Lead must have overlapping brands
    requires_adjacent_brands = Column(Boolean)

    # Output
    primary_angle = Column(String(50), nullable=False)
    secondary_angle = Column(String(50))
    brand_query = Column(JSON)                        # Filter template for brand matching
    description = Column(Text)


class ObjectionsKB(Base):
    """Approved objection response templates. AI cannot invent rebuttals."""
    __tablename__ = "objections_kb"

    id = Column(Integer, primary_key=True, autoincrement=True)
    objection_type = Column(String(100), unique=True, nullable=False)
    pattern_keywords = Column(JSON, default=list)     # Keywords to match
    template_subject = Column(String(500))
    template_body = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    version = Column(String(20), default="v1")
    notes = Column(Text)


class Config(Base):
    """Runtime config stored in DB for consistency."""
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(200), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Pydantic Schemas ──────────────────────────────────────────────

class LeadCreateRequest(BaseModel):
    company_name: str
    website_url: Optional[str] = None
    contact_email: str
    channel: Optional[str] = None
    niche: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class LeadClassifierOutput(BaseModel):
    """Strict JSON schema for AI lead classifier output."""
    brand_list: list[str] = Field(default_factory=list)
    private_label_ratio: float = 0.0
    price_tier: str = "mixed"
    scale_score: int = 0
    map_behavior_score: int = 0
    store_count: int = 0
    qualifies: bool = True
    disqualify_reason: Optional[str] = None


class ReplyClassifierOutput(BaseModel):
    """Strict JSON schema for AI reply classifier output."""
    classification: str
    objection_type: Optional[str] = None
    action: str
    interest_level: int = 0


class PipelineStats(BaseModel):
    total_leads: int = 0
    new: int = 0
    researched: int = 0
    qualified: int = 0
    disqualified: int = 0
    contacted: int = 0
    replied: int = 0
    interested: int = 0
    objections: int = 0
    booked: int = 0
    dead: int = 0
    total_emails_sent: int = 0
    total_replies: int = 0
    conversion_rate: float = 0.0


# ── Init Database ─────────────────────────────────────────────────

def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
