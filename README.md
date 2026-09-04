# RecoverX

RecoverX is an AI-driven revenue recovery control plane for Razorpay merchants. It runs the complete recovery loop against a deterministic Simulated Razorpay environment: signed webhook ingestion, canonical event normalization, deterministic risk scoring, LangGraph recommendation, policy-gated tool execution, customer payment simulation, audit history, and database-backed analytics.

## Run locally

```powershell
cd frontend
npm run dev
```

Open http://localhost:3000. The backend can be started with:

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

The API health check is available at http://localhost:8000/health.

For the seeded local demo, sign in with `admin@recoverx.local` / `recoverx-demo`, then use **Simulator** to trigger an event and complete the customer recovery payment flow.

## Verification

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm.cmd run lint
npm.cmd run build
```

For critical browser checks, start the backend and frontend first, then run:

```powershell
cd frontend
npx playwright install chromium
npm.cmd run e2e
```

Set `PLAYWRIGHT_BASE_URL` to a deployed RecoverX URL to run the same smoke tests against Render.

## Docker

```powershell
docker compose up --build
```

## Render

`render.yaml` defines the frontend, FastAPI API, Redis, and PostgreSQL services. In Render, create a Blueprint from this repository, then provide `RAZORPAY_WEBHOOK_SECRET` and any live integration credentials as secret environment variables. The included UI uses synthetic data until those providers are configured.

Set `NEXT_PUBLIC_API_URL` to the complete HTTPS API URL and `CORS_ORIGINS` to the complete HTTPS frontend URL in Render. These are intentionally manual deployment values so the browser never receives a scheme-less host.

Financial actions must pass through the policy gate in the backend before a provider call is added. Razorpay remains the financial source of truth; AI only reasons over normalized backend data.
