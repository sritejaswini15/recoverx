# RecoverX

**AI Revenue Recovery Control Plane for Razorpay merchants.**

RecoverX detects revenue-risk events, runs deterministic risk scoring, produces AI-reasoned recovery strategies (LangGraph), enforces merchant policy guardrails, executes controlled payment and communication actions, and closes the loop through webhooks — all backed by PostgreSQL as the financial source of truth.

---

## Architecture

```
Revenue-risk event
  → Webhook (HMAC-SHA256 verified, deduplicated)
  → Event normalizer (canonical revenue event)
  → Risk Engine (deterministic score, recovery probability, expected value)
  → LangGraph Agent (diagnosis, root cause, strategy, confidence)
  → Policy Engine (auto-approve / human-review / stop)
  → Tool Gateway (idempotency, authorization, provider abstraction)
  → Simulated or Live Razorpay (payment link, retry, communication)
  → Success webhook → case RECOVERED → analytics updated → audit trail
```

**Core boundaries:**

| Layer | Role |
|---|---|
| PostgreSQL | Financial and business truth |
| LangGraph | Stateful AI reasoning |
| Risk Engine | Deterministic financial intelligence |
| Policy Engine | Authorization and guardrails |
| Tool Gateway | Controlled action boundary |
| MCP Server | Standardized tool interface |
| Simulated Razorpay | Development / demo external provider |
| Razorpay | Production payment infrastructure |
| Temporal | Durable workflow execution (optional) |

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 18+
- A virtual environment at `.venv/` (already set up if cloned from repo)

### Backend

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

On first startup the API seeds 1 000 synthetic customers and 500 recovery cases.

**Sign in:** `admin@recoverx.local` / `recoverx-demo` *(LOCAL DEVELOPMENT ONLY — never use in production)*

Health check: http://localhost:8000/health  
API docs: http://localhost:8000/docs

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

---

## Verification

```powershell
# Backend tests (32 tests)
.venv\Scripts\python.exe -m pytest backend\tests\ -v

# Frontend lint
cd frontend
npm run lint

# Frontend production build
npm run build

# 500-case batch evaluation
.venv\Scripts\python.exe backend\scripts\run_batch_evaluation.py
```

---

## End-to-End Tests (Playwright)

Requires the backend and frontend running:

```powershell
cd frontend
npx playwright install chromium
npm run e2e
```

Tests cover the complete golden demo path: login → dashboard → simulation → case → diagnosis → policy → recovery action → customer payment → webhook → RECOVERED state → analytics.

---

## Docker (Local)

```powershell
docker compose up --build
```

---

## Simulation

The **Simulation Center** (`/simulation`) lets you:

1. **Trigger a payment failure** — generates a signed webhook, creates a recovery case, runs the full AI → policy → tool pipeline
2. **Simulate Pay Now** — the customer clicks the payment link, completing the recovery loop
3. **Test failure paths** — provider timeout, low AI confidence escalation, customer opt-out, max contact attempts

All simulated events use the same code paths as live Razorpay webhooks. Signatures are HMAC-SHA256 verified; deduplication prevents replay attacks.

---

## 500-Case Evaluation

Run the complete evaluation benchmark against the seeded dataset:

```powershell
.venv\Scripts\python.exe backend\scripts\run_batch_evaluation.py
```

Or trigger via the UI: **Command Center → Run recovery scan**.

Metrics reported:
- Cases processed, revenue at risk, revenue recovered, recovery rate
- Strategy distribution and per-strategy performance
- Policy violations, escalations, false escalations
- AI decision accuracy and average confidence
- Average recovery time

---

---

## Deployment (Railway & Render)

RecoverX is containerized and deployable to both **Railway** and **Render**.

### Railway Deployment (Recommended)

1. Create a new project in [Railway](https://railway.app/).
2. Add **PostgreSQL** (`recoverx-postgres`) and **Redis** services. Railway automatically provides `DATABASE_URL` and `REDIS_URL`.
3. Add **GitHub Repo Service** pointing to `sritejaswini15/recoverx`:
   - **Backend API**:
     - Root Directory: `backend`
     - Dockerfile is automatically detected
     - Variables:
       - `ENVIRONMENT=production`
       - `SEED_DEMO_DATA=true` (for automatic 1,000 customers & 500 cases seeding on initial boot)
       - `AUTH_REQUIRED=true`
       - `PAYMENT_PROVIDER=simulated`
       - `LLM_PROVIDER=deterministic`
       - `TEMPORAL_ENABLED=false`
       - `AUTH_SECRET=<32+ random characters>`
       - `RAZORPAY_WEBHOOK_SECRET=<32+ characters or recoverx_webhook_secret_key_2026>`
       - `BOOTSTRAP_ADMIN_EMAIL=admin@yourdomain.com`
       - `BOOTSTRAP_ADMIN_PASSWORD=<16+ char password>`
       - `BOOTSTRAP_RAZORPAY_ACCOUNT_ID=acct_railway_demo`
       - `CORS_ORIGINS=https://<your-frontend>.up.railway.app`
   - **Frontend UI**:
     - Root Directory: `frontend`
     - Dockerfile is automatically detected
     - Variables:
       - `NEXT_PUBLIC_API_URL=https://<your-api>.up.railway.app`
4. Both services run in the foreground and bind to `PORT` supplied by Railway.
5. Migrations run automatically on startup via `alembic upgrade head`.

### Render Deployment

`render.yaml` defines all Render services: FastAPI backend, Next.js frontend, managed PostgreSQL, Redis/Key-Value, and daily cleanup cron. Create a Render Blueprint from this repository and supply required `sync: false` secrets in settings.

---

## Environment Variables

See `.env.example` for development defaults and `.env.production.example` for all production-required variables with documentation.

Key variables:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Production | PostgreSQL connection string |
| `AUTH_SECRET` | Production | Token signing secret |
| `RAZORPAY_WEBHOOK_SECRET` | Production | Webhook HMAC secret |
| `BOOTSTRAP_ADMIN_EMAIL` | Production | First admin user |
| `BOOTSTRAP_ADMIN_PASSWORD` | Production | First admin password |
| `CORS_ORIGINS` | Production | Allowed frontend origins |
| `NEXT_PUBLIC_API_URL` | Frontend | Backend API URL |

---

## Security

- All authenticated endpoints require a valid Bearer token (HMAC-SHA256 signed, 8-hour TTL)
- All financial actions require ADMIN, FINANCE_MANAGER, or OPERATOR role
- Tenant isolation is enforced server-side — organization_id scopes every query
- Webhook signatures are verified before any processing
- Policy Engine gates all financial actions; AI cannot bypass it
- Production secrets are validated at startup; example credentials cause immediate rejection

---

## Documentation

Detailed documentation is in the `docs/` directory:

| File | Contents |
|---|---|
| `ARCHITECTURE.md` | System architecture and data flows |
| `API.md` | API reference |
| `COMPLETE_IMPLEMENTATION_GUIDE.md` | Full implementation details |
| `DEPLOYMENT.md` | Deployment guide |
| `PRODUCTION_DEPLOYMENT.md` | Production checklist |
| `TESTING.md` | Testing strategy |
| `IMPLEMENTATION_AUDIT.md` | Final implementation audit |
| `DEFINITION_OF_DONE.md` | Golden demo definition of done |
