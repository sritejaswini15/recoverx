# Build Spec

The repository is a modular monolith: FastAPI and SQLAlchemy backend, Next.js frontend, PostgreSQL in deployment, and SQLite for local fallback. `CaseService` owns event normalization and case creation; `RiskEngine` performs deterministic financial math; the recovery graph provides structured reasoning; `PolicyEngine` authorizes; `ToolGateway` is the only external-action boundary.

Run backend with `uvicorn app.main:app --reload` from `backend`. Run frontend with `npm run dev` from `frontend`. Seed deterministically with `python scripts/seed_synthetic_data.py`.