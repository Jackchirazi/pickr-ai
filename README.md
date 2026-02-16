# Pickr AI Email Sales Rep

An AI-powered outbound sales system that researches leads, generates personalized cold emails, handles objections, manages follow-up sequences, and books meetings — all automatically.

---

## What This Does

1. **Imports leads** (CSV upload or API) with company name, email, storefront URL
2. **Scrapes & analyzes** their storefront to understand what brands they carry, their price tier, channel, and scale
3. **Qualifies** leads automatically (disqualifies private-label-only sellers)
4. **Selects the best sales angle** for each lead (expansion, alignment, stability, scalability, institutional, or growth)
5. **Generates personalized emails** using AI with the Pickr executive voice
6. **Runs a 5-touch follow-up sequence** with different angles and timing
7. **Handles objections** from replies using a knowledge base + AI
8. **Books meetings** by detecting interest and sending your calendar link
9. **Provides a dashboard** to monitor the entire pipeline

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- An Anthropic API key (for Claude AI) — get one at https://console.anthropic.com
- An email account for sending (Gmail with app password works for testing)
- A Google Calendar appointment link

### 2. Install

```bash
cd pickr-ai
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env` with your values:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
SENDER_NAME=Your Name
SENDER_EMAIL=your-email@gmail.com
BOOKING_LINK=https://calendar.google.com/calendar/appointments/your-link
```

**Gmail App Password:** Go to Google Account → Security → 2-Step Verification → App Passwords → Generate one for "Mail".

### 4. Initialize & Run

```bash
# Initialize the database
python main.py init

# Start the dashboard
python main.py serve
```

Open http://localhost:8000 in your browser.

---

## Usage

### Import Leads

**Via CSV upload** on the dashboard, or:

```bash
python main.py import data/sample_leads.csv
```

CSV columns: `company_name`, `email`, `storefront_url`, `niche`, `location`

**Via API:**

```bash
curl -X POST http://localhost:8000/api/leads \
  -H "Content-Type: application/json" \
  -d '{"company_name": "Example Store", "email": "buyer@example.com", "storefront_url": "https://example.com", "niche": "beauty"}'
```

### Process Leads

```bash
# Enrich + qualify all new leads
python main.py process

# Send first-touch emails to qualified leads
python main.py send

# Process follow-up emails (run daily via cron)
python main.py followups
```

### Preview Emails (Without Sending)

```bash
python main.py preview 1 1   # Preview Touch 1 for lead ID 1
python main.py preview 1 3   # Preview Touch 3 for lead ID 1
```

### Handle Replies

```bash
python main.py reply 1 "We already have a supplier for those brands"
```

Or via API:

```bash
curl -X POST http://localhost:8000/api/leads/1/reply \
  -d "reply_text=Margins aren't high enough for us"
```

### Check Stats

```bash
python main.py stats
```

---

## Automation (Cron Jobs)

To run this automatically, set up cron jobs:

```bash
# Edit crontab
crontab -e

# Process new leads every hour
0 * * * * cd /path/to/pickr-ai && python main.py process

# Send pending emails every 2 hours (during business hours)
0 9-17/2 * * 1-5 cd /path/to/pickr-ai && python main.py send

# Process follow-ups daily at 10am
0 10 * * 1-5 cd /path/to/pickr-ai && python main.py followups
```

---

## Architecture

```
pickr-ai/
├── main.py                          # CLI entry point
├── pickr/
│   ├── config.py                    # Environment configuration
│   ├── models.py                    # Database models + schemas
│   ├── pipeline.py                  # Main orchestrator
│   ├── enrichment/
│   │   ├── scraper.py               # Storefront web scraper
│   │   └── analyzer.py              # AI-powered lead analysis
│   ├── engine/
│   │   ├── leverage.py              # Sales angle selection
│   │   ├── email_generator.py       # AI email writer
│   │   ├── objection_handler.py     # Objection brain
│   │   └── follow_up.py             # 5-touch sequencer
│   ├── catalog/
│   │   └── matcher.py               # Brand matching + priority
│   ├── integrations/
│   │   └── email_sender.py          # SMTP email sending
│   └── web/
│       └── dashboard.py             # Dashboard + API
├── data/
│   ├── objections.json              # Objection knowledge base
│   └── sample_leads.csv             # Sample lead data
├── requirements.txt
└── .env.example
```

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard UI |
| `/api/leads` | GET | List leads |
| `/api/leads` | POST | Create single lead |
| `/api/leads/bulk` | POST | Create multiple leads |
| `/api/leads/upload-csv` | POST | Upload CSV file |
| `/api/leads/{id}` | GET | Get lead details |
| `/api/leads/{id}/emails` | GET | Get lead's email history |
| `/api/leads/{id}/reply` | POST | Handle inbound reply |
| `/api/leads/{id}/preview-email/{touch}` | GET | Preview email |
| `/api/pipeline/process-new` | GET | Process new leads |
| `/api/pipeline/send-emails` | GET | Send pending emails |
| `/api/pipeline/followups` | GET | Process follow-ups |
| `/api/pipeline/stats` | GET | Pipeline statistics |

---

## Email Deliverability (Critical)

Before sending at scale, you MUST set up:

1. **Dedicated sending domain** — Don't send from your main domain. Use something like `mail.pickr.com`
2. **SPF record** — Add a DNS TXT record authorizing your email server
3. **DKIM signing** — Set up DomainKeys for email authentication
4. **DMARC policy** — Add a DMARC record to prevent spoofing
5. **Domain warmup** — Start with 10-20 emails/day, increase by 10-20% weekly over 4-6 weeks
6. **Dedicated IP** (optional) — For high volume, get a dedicated sending IP

The system includes rate limiting. Adjust `daily_limit` in `email_sender.py` as you warm up.

---

## Customization

### Adding Brands to the Catalog

Edit the brand catalog via the database or add to `DEFAULT_BRANDS` in `catalog/matcher.py`.

### Adding Objection Responses

Add entries to `data/objections.json`. Format:

```json
{
    "objection_key": {
        "pattern": ["keyword1", "keyword2", "phrase to match"],
        "response_template": "Your confident response here.",
        "category": "pricing|logistics|competition|timing|trust|compliance"
    }
}
```

### Adjusting Follow-Up Timing

Edit `FOLLOWUP_TIMING` in `config.py` (values are in hours).

### Changing the AI Voice

Edit `PERSONALITY_SYSTEM` in `engine/email_generator.py`.

---

## Deployment Options

### Simple (Single Server)

1. Get a VPS (DigitalOcean $6/mo, Railway, or Render)
2. Clone the repo, install deps, configure `.env`
3. Run `python main.py serve` (use `screen` or `systemd` to keep alive)
4. Set up cron jobs for automation

### With Docker (Recommended)

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "serve"]
```

---

## Connecting to Your CRM (Hercules)

The system uses a local SQLite database by default. To sync with your Hercules CRM:

1. **Export from Hercules** → CSV → Upload to Pickr
2. **API integration** — If Hercules has an API, add a sync module in `pickr/integrations/`
3. **Webhook** — Set up Hercules to POST new leads to `POST /api/leads`

The most practical starting approach is option 1 (CSV export/import) while you validate the system works.

---

## Cost Estimates

- **Anthropic API**: ~$0.01-0.05 per lead (enrichment + email generation)
- **Hosting**: $6-20/month (VPS or cloud)
- **Email sending**: Free with Gmail (up to 500/day) or $15-30/mo for SendGrid/Mailgun
- **At 1,000 leads/month**: Roughly $50-100/month total

---

## Important Notes

- Always test with a small batch first (5-10 leads)
- Preview emails before enabling auto-send
- Monitor spam complaints and bounce rates
- Keep the daily send volume conservative during warmup
- The AI generates unique emails every time — review a sample batch for quality
- Add your own objection responses to `data/objections.json` as you encounter new ones
