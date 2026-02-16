"""
Pickr AI - Configuration
Central configuration loaded from environment variables.
Aligned with Haim's 82-step spec: PostgreSQL + Redis + SmartLead/Instantly.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

# ── Database (PostgreSQL) ────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pickr:pickr@localhost:5432/pickr"
)
# SQLAlchemy needs postgresql:// not postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Redis (Job Queue) ───────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── LLM ──────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")

# ── Email Provider ───────────────────────────────────────────────
# Primary: SmartLead or Instantly (NOT raw SMTP)
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smartlead")  # "smartlead" or "instantly"

# SmartLead
SMARTLEAD_API_KEY = os.getenv("SMARTLEAD_API_KEY", "")
SMARTLEAD_BASE_URL = os.getenv("SMARTLEAD_BASE_URL", "https://server.smartlead.ai/api/v1")

# Instantly
INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY", "")
INSTANTLY_BASE_URL = os.getenv("INSTANTLY_BASE_URL", "https://api.instantly.ai/api/v1")

# Webhook secret for provider callbacks
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Sender identity (used in provider campaigns)
SENDER_NAME = os.getenv("SENDER_NAME", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")

# ── Booking / Calendar ───────────────────────────────────────────
BOOKING_LINK = os.getenv(
    "BOOKING_LINK",
    "https://calendar.app.google/XaD2Fd9iUj5jtFrv8"
)

# ── App ──────────────────────────────────────────────────────────
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
SCHEMA_VERSION = "2026_02_15_001"

# ── Follow-up Timing (hours) ────────────────────────────────────
FOLLOWUP_TIMING = {
    1: 0,       # Touch 1: Immediate
    2: 24,      # Touch 2: Next day
    3: 96,      # Touch 3: 3 days later
    4: 168,     # Touch 4: 1 week later
    5: 720,     # Touch 5: 1 month later
}

# ── Meeting Details ──────────────────────────────────────────────
MEETING_DURATION = "30 min"
MEETING_DAYS = "Mon-Thu"
MEETING_HOURS = "11am-4pm EST"
MEETING_TITLE_TEMPLATE = "Pickr x {company_name}"

# ── Operational Limits ───────────────────────────────────────────
MAX_BRANDS_PER_EMAIL = 3          # Hard cap: never more than 3 brands
MAX_CURATED_SHEETS = 3            # Hard cap: 1-3 curated sheets only
MAX_REPAIR_RETRIES = 1            # AI JSON repair: 1 retry then fail
HUMAN_APPROVAL_THRESHOLD = 200    # First N replies need human approval
SCRAPE_BUDGET_MS = 25000          # Max scrape time per lead
SCRAPE_MAX_PAGES = 6              # Max pages to scrape per site
RATE_LIMIT_PER_DOMAIN_PER_DAY = 50  # Email rate limit

# ── Forbidden Phrases ────────────────────────────────────────────
# These MUST NEVER appear in any outbound email
FORBIDDEN_PHRASES = [
    "cost basis",
    "invoice",
    "exclusivity",
    "exclusive deal",
    "full catalog",
    "complete catalog",
    "entire catalog",
    "detailed margin",
    "margin structure",
    "percent off",
    "% off retail",
    "wholesale price",
    "wholesale cost",
    "our cost",
    "your cost",
    "cost per unit",
    "direct authorized",
    "authorized distributor",
    "MAP violation",
    "below MAP",
    "grey market",
    "gray market",
    "diversion",
    "liquidation",
]

# ── Allowed Actions (closed set) ────────────────────────────────
ALLOWED_REPLY_ACTIONS = [
    "send_calendar",
    "send_curated_catalog",
    "suppress",
    "handoff_to_human",
]
