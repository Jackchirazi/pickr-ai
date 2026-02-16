# Deploy Pickr AI v2 — Step by Step

Production architecture: PostgreSQL + Redis + SmartLead/Instantly.

---

## Option A: Local Development (Docker Compose)

### Prerequisites
- Docker Desktop installed
- Anthropic API key
- SmartLead or Instantly API key

### Steps

1. **Clone and configure:**
```bash
git clone https://github.com/Jackchirazi/pickr-ai.git
cd pickr-ai
cp .env.example .env
# Edit .env with your API keys
```

2. **Start everything:**
```bash
docker-compose up --build
```

This starts:
- PostgreSQL on port 5432
- Redis on port 6379
- Pickr API + Dashboard on port 8000
- Background worker (polls every 30s)

3. **Open the dashboard:**
```
http://localhost:8000
```

4. **Seed the database (first time):**
```bash
docker-compose exec api python main.py seed
```

---

## Option B: Railway (Production)

### Step 1: Create Railway Account
1. Go to https://railway.app and sign in with GitHub

### Step 2: Add PostgreSQL
1. Click **New Project** → **Provision PostgreSQL**
2. Copy the `DATABASE_URL` from the Variables tab

### Step 3: Add Redis
1. In the same project, click **+ New** → **Database** → **Redis**
2. Copy the `REDIS_URL`

### Step 4: Deploy the API
1. Click **+ New** → **GitHub Repo** → select `pickr-ai`
2. Railway will detect the Dockerfile and build
3. Add these environment variables:

```
ANTHROPIC_API_KEY        = sk-ant-your-key-here
EMAIL_PROVIDER           = smartlead
SMARTLEAD_API_KEY        = your-smartlead-api-key
WEBHOOK_SECRET           = your-random-secret
SENDER_NAME              = Your Name
SENDER_EMAIL             = your-email@pickr.com
BOOKING_LINK             = https://calendar.app.google/your-link
DATABASE_URL             = (auto-filled by Railway PostgreSQL)
REDIS_URL                = (auto-filled by Railway Redis)
```

4. Go to **Settings** → **Networking** → **Generate Domain**
5. You'll get a URL like `pickr-ai-production.up.railway.app`

### Step 5: Deploy the Worker
1. In the same project, click **+ New** → **GitHub Repo** → select `pickr-ai` again
2. Override the start command: `python -m pickr.scheduler 30`
3. Add the same environment variables (reference the same DB and Redis)

### Step 6: Configure Webhooks
In SmartLead/Instantly, set the webhook URL to:
```
https://your-domain.up.railway.app/webhooks/provider
```

---

## Step 7: Test It

1. Open your Railway URL — you should see the dashboard
2. Upload `data/sample_leads.csv` or create a lead via API:
```bash
curl -X POST https://your-domain.up.railway.app/api/leads \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Test Store",
    "website_url": "https://example-store.com",
    "contact_email": "test@example.com",
    "channel": "amazon",
    "niche": "health"
  }'
```
3. Process the lead:
```bash
curl -X POST https://your-domain.up.railway.app/api/pipeline/process
```

---

## Daily Usage

Once deployed, the worker runs automatically:
- Polls for queued jobs every 30 seconds
- Processes leads through the full pipeline
- SmartLead/Instantly handle actual email delivery

What you do:
1. Upload new lead CSVs when you have them
2. Check the dashboard for replies needing approval
3. Approve/reject AI-drafted responses
4. Take the meetings it books

---

## API Quick Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard |
| `/health` | GET | Health check |
| `/api/leads` | GET/POST | List/create leads |
| `/api/leads/csv` | POST | Upload CSV |
| `/api/leads/{id}` | GET | Lead detail |
| `/api/leads/{id}/outcome` | POST | Set outcome |
| `/api/leads/{id}/book` | POST | Mark booked |
| `/api/pipeline/process` | POST | Process queue |
| `/api/stats` | GET | Pipeline stats |
| `/api/replies/pending` | GET | Pending approvals |
| `/api/replies/{id}/approve` | POST | Approve reply |
| `/api/replies/{id}/reject` | POST | Reject reply |
| `/api/suppress` | POST | Suppress email |
| `/api/audit` | GET | Audit log |
| `/webhooks/provider` | POST | Provider webhooks |

---

## Costs

- **Railway**: ~$5/month (PostgreSQL + Redis + 2 services)
- **Anthropic API**: ~$0.02-0.05 per lead processed. 1,000 leads = $20-50
- **SmartLead**: Starts at $39/month (2,000 leads)
- **Instantly**: Starts at $30/month (5,000 emails)

---

## Troubleshooting

**Dashboard won't load:**
Check Railway logs. Usually a missing environment variable.

**Worker not processing:**
Check the worker service logs. Make sure DATABASE_URL matches the API service.

**Leads stuck at "new":**
The worker needs to be running. Check `python -m pickr.scheduler` logs.

**Webhooks not working:**
- Verify the webhook URL is correct in SmartLead/Instantly
- Check Railway logs for incoming webhook requests
- Make sure WEBHOOK_SECRET matches if provider requires it
