"""RecoverX FastAPI Application.
AI Revenue Recovery Control Plane for Razorpay merchants.
Authoritative REST APIs, Webhook pipeline, Simulation center, and MCP interface.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.auth import current_user, hash_password, issue_token, require_roles, revoke_token, verify_password
from app.core.config import settings
from app.db import (
    AuditEvent,
    AgentDecision,
    Communication,
    Customer,
    Escalation,
    Invoice,
    Organization,
    Payment,
    PaymentAttempt,
    PaymentLink,
    Policy,
    PromiseToPay,
    RecoveryAction,
    RecoveryCase,
    RevenueEvent,
    WebhookReceipt,
    RiskAssessment,
    Subscription,
    User,
    get_session,
    init_db, utc_now,
)
from app.mcp import mcp_server
from app.providers import SimulatedRazorpayProvider
from app.services.analytics_service import AnalyticsService
from app.services.case_service import CaseService
from app.services.evaluation_service import EvaluationService
from app.services.policy_engine import PolicyEngine
from app.services.risk_engine import RiskEngine
from app.services.tool_gateway import default_gateway
from app.simulation.generator import generate_synthetic_dataset
from app.workflows import workflow_runner

@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ARG001
    settings.validate_production()
    # Schema changes are applied by Alembic in the production container.  The
    # metadata helper remains a developer/test convenience only.
    if settings.ENVIRONMENT.lower() != "production":
        init_db()
    session = next(get_session())
    try:
        if settings.BOOTSTRAP_ADMIN_EMAIL:
            admin_email = settings.BOOTSTRAP_ADMIN_EMAIL.strip().lower()
            admin_pwd = (settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip()
            admin = session.scalar(select(User).where(User.email == admin_email))
            if not admin:
                org = session.scalar(select(Organization).limit(1))
                if not org:
                    org = Organization(name=settings.BOOTSTRAP_ORGANIZATION_NAME, razorpay_account_id=settings.BOOTSTRAP_RAZORPAY_ACCOUNT_ID)
                    session.add(org)
                    session.flush()
                session.add(User(
                    organization_id=org.id,
                    email=admin_email,
                    name="Bootstrap Administrator",
                    role="ADMIN",
                    password_hash=hash_password(admin_pwd) if admin_pwd else None
                ))
                session.commit()
            elif admin_pwd and not verify_password(admin_pwd, admin.password_hash):
                # Ensure the Railway/environment-configured bootstrap credentials remain valid
                # if the environment variable was updated or if an earlier run created a stale hash.
                admin.password_hash = hash_password(admin_pwd)
                admin.role = "ADMIN"
                session.commit()
        if settings.SEED_DEMO_DATA and session.scalar(select(func.count(Customer.id))) == 0:
            generate_synthetic_dataset(session, customer_count=1000, case_count=500, seed=20260902)
    finally:
        session.close()
    yield


app = FastAPI(
    title="RecoverX API",
    description="AI Revenue Recovery Control Plane for Razorpay merchants",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---

class PolicyPayload(BaseModel):
    max_auto_action_amount: int = Field(25000, ge=0)
    human_approval_above_amount: int = Field(25000, ge=0)
    max_contact_attempts: int = Field(3, ge=0)
    escalate_after_days: int = Field(7, ge=0)
    min_ai_confidence: float = Field(0.70, ge=0.0, le=1.0)
    preferred_channels: str = "whatsapp,email"
    supported_languages: str = "English,Hinglish"


class BatchRequest(BaseModel):
    customers: int = Field(1000, ge=1, le=10000)
    cases: int = Field(500, ge=1, le=10000)
    seed: int = 20260902


class SimulationRequest(BaseModel):
    case_id: str | None = None
    customer_id: str | None = None


class PromisePayload(BaseModel):
    case_id: str
    amount: int = Field(gt=0)
    promised_date: datetime
    notes: str | None = None


class EventPayload(BaseModel):
    event_type: str
    customer_id: str | None = None
    amount: int = Field(0, ge=0)
    currency: str = "INR"
    id: str | None = None
    source_entity: str = "payment"


class ResolutionPayload(BaseModel):
    resolution: str = Field(min_length=2, max_length=64)  # APPROVE, REJECT, EDIT, CONTACT, CLOSE
    notes: str | None = None


def _process_simulated_webhook(
    session: Session,
    org: Organization,
    customer: Customer,
    webhook_payload: Any,
    actor: str,
) -> tuple[RevenueEvent, RecoveryCase | None, bool]:
    """Run simulated provider responses through the same signed receipt path."""
    raw_payload = webhook_payload.raw_body
    # The provider owns the secret; verify against the configured secret just as
    # the public webhook endpoint does.
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "recoverx_webhook_secret_key_2026")
    expected_signature = hmac.new(secret.encode("utf-8"), raw_payload, sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, webhook_payload.signature):
        raise HTTPException(status_code=502, detail="Simulated webhook signature invalid")

    body = json.loads(raw_payload.decode("utf-8"))
    provider_event_id = body.get("id")
    if not isinstance(provider_event_id, str) or not provider_event_id:
        raise HTTPException(status_code=502, detail="Simulated webhook event id missing")
    dedupe_key = f"razorpay:event:{provider_event_id}"
    receipt = session.scalar(
        select(WebhookReceipt).where(
            WebhookReceipt.organization_id == org.id,
            WebhookReceipt.provider_event_id == provider_event_id,
        )
    )
    if receipt and receipt.revenue_event_id:
        event = session.get(RevenueEvent, receipt.revenue_event_id)
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.revenue_event_id == receipt.revenue_event_id))
        if event:
            return event, case, True
    if not receipt:
        receipt = WebhookReceipt(
            organization_id=org.id,
            provider_event_id=provider_event_id,
            dedupe_key=dedupe_key,
            raw_payload=body,
        )
        session.add(receipt)
        session.flush()

    event, case, duplicate = CaseService.process_event(
        session=session,
        org=org,
        customer=customer,
        raw_body=body,
        dedupe_key=dedupe_key,
        actor=actor,
    )
    receipt.status = "PROCESSED"
    receipt.revenue_event_id = event.id
    receipt.processed_at = datetime.now(timezone.utc)
    return event, case, duplicate


class LoginPayload(BaseModel):
    email: str
    password: str


_login_attempts: dict[str, list[datetime]] = {}


class MCPRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


# --- Helper Methods ---

def get_org(session: Session, organization_id: str | None = None) -> Organization:
    org = session.scalar(
        select(Organization).where(Organization.id == organization_id).limit(1)
        if organization_id
        else select(Organization).limit(1)
    )
    if not org:
        org = Organization(id=str(uuid4()), name="RecoverX Demo Merchant", currency="INR", timezone="Asia/Kolkata")
        session.add(org)
        session.flush()
    return org


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def serialize_case(case: RecoveryCase) -> dict[str, Any]:
    risk = case.risk_assessment
    event = case.revenue_event
    return {
        "id": case.id,
        "customer_id": case.customer_id,
        "customer": case.customer.name if case.customer else "Unknown",
        "customer_phone": case.customer.phone if case.customer else "",
        "customer_email": case.customer.email if case.customer else "",
        "customer_reliability": case.customer.payment_reliability_pct if case.customer else 85.0,
        "preferred_channel": case.customer.preferred_channel if case.customer else "whatsapp",
        "preferred_language": case.customer.preferred_language if case.customer else "English",
        "event_type": event.event_type if event else "PAYMENT_FAILURE",
        "amount": case.amount,
        "currency": case.currency,
        "risk_score": risk.risk_score if risk else 50,
        "recovery_probability": risk.recovery_probability if risk else 0.5,
        "expected_recovery_value": risk.expected_recovery_value if risk else case.amount // 2,
        "ai_confidence": case.ai_confidence,
        "policy_decision": case.policy_decision,
        "recommended_action": case.recommended_action,
        "status": case.status,
        "contact_attempts": case.contact_attempts,
        "recovered_amount": case.recovered_amount,
        "action_executed": case.action_executed,
        "failure_reason": case.failure_reason,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
    }


def serialize_customer(customer: Customer) -> dict[str, Any]:
    return {
        "id": customer.id,
        "razorpay_customer_id": customer.razorpay_customer_id,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "lifetime_value": customer.lifetime_value,
        "successful_payments": customer.successful_payments,
        "failed_payments": customer.failed_payments,
        "payment_reliability_pct": customer.payment_reliability_pct,
        "preferred_channel": customer.preferred_channel,
        "preferred_language": customer.preferred_language,
        "historical_recovery_rate": customer.historical_recovery_rate,
        "opted_out": customer.opted_out,
        "created_at": customer.created_at.isoformat(),
    }



# --- Lifespan & Health ---


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(select(1))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable") from exc
    return {
        "status": "ok",
        "service": "recoverx-control-plane",
        "mode": "simulation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/integrations/status")
def integrations_status(_user: User = Depends(current_user)) -> dict[str, Any]:
    """Report truthful integration state.
    SIMULATED = running in simulated mode (no real credentials)
    CONNECTED = real credentials configured
    NOT_CONFIGURED = credentials absent
    """
    razorpay_key = os.getenv("RAZORPAY_KEY_ID", "")
    razorpay_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    llm_openai = os.getenv("OPENAI_API_KEY", "")
    llm_anthropic = os.getenv("ANTHROPIC_API_KEY", "")
    whatsapp = os.getenv("WHATSAPP_PROVIDER_TOKEN", "")
    email_key = os.getenv("EMAIL_PROVIDER_API_KEY", "")
    temporal_host = os.getenv("TEMPORAL_HOST", "")
    temporal_enabled = os.getenv("TEMPORAL_ENABLED", "false").lower() == "true"
    sentry_dsn = os.getenv("SENTRY_DSN", "")

    def _rzp() -> dict[str, str]:
        if razorpay_key and razorpay_secret:
            return {"status": "CONNECTED", "label": "Connected", "detail": "Live Razorpay credentials configured"}
        return {"status": "SIMULATED", "label": "Simulated", "detail": "Using SimulatedRazorpayProvider — no live credentials"}

    def _llm() -> dict[str, str]:
        if llm_openai:
            return {"status": "CONNECTED", "label": "Connected", "detail": f"OpenAI key configured ({llm_openai[:8]}…)"}
        if llm_anthropic:
            return {"status": "CONNECTED", "label": "Connected", "detail": f"Anthropic key configured ({llm_anthropic[:8]}…)"}
        return {"status": "SIMULATED", "label": "Simulated", "detail": "Deterministic LangGraph agent — no LLM API key"}

    def _comm(token: str, name: str) -> dict[str, str]:
        if token:
            return {"status": "CONNECTED", "label": "Connected", "detail": f"{name} provider token configured"}
        return {"status": "SIMULATED", "label": "Simulated", "detail": f"Using Simulated{name}Provider"}

    def _temporal() -> dict[str, str]:
        if temporal_enabled and temporal_host:
            return {"status": "CONNECTED", "label": "Connected", "detail": f"Temporal at {temporal_host}"}
        if temporal_enabled:
            return {"status": "NOT_CONFIGURED", "label": "Not configured", "detail": "TEMPORAL_ENABLED=true but TEMPORAL_HOST not set"}
        return {"status": "SIMULATED", "label": "Simulated", "detail": "In-process runner (set TEMPORAL_ENABLED=true for durable workflows)"}

    integrations = [
        {"name": "Razorpay", "category": "Payment", **_rzp()},
        {"name": "RecoverX Webhooks", "category": "Webhooks", "status": "CONNECTED", "label": "Active", "detail": "POST /webhooks/razorpay with HMAC-SHA256 verification"},
        {"name": "RecoverX MCP Server", "category": "MCP", "status": "CONNECTED", "label": "Active", "detail": "15 read+write tools behind policy boundary"},
        {"name": "WhatsApp", "category": "Communication", **_comm(whatsapp, "WhatsApp")},
        {"name": "Email", "category": "Communication", **_comm(email_key, "Email")},
        {"name": "Temporal", "category": "Workflows", **_temporal()},
        {"name": "LLM Provider", "category": "AI", **_llm()},
        {"name": "Sentry", "category": "Observability", **(
            {"status": "CONNECTED", "label": "Connected", "detail": "Error reporting active"}
            if sentry_dsn else
            {"status": "NOT_CONFIGURED", "label": "Not configured", "detail": "Set SENTRY_DSN to enable error reporting"}
        )},
    ]
    return {
        "integrations": integrations,
        "counts": {
            "total": len(integrations),
            "simulated": sum(1 for i in integrations if i["status"] == "SIMULATED"),
            "connected": sum(1 for i in integrations if i["status"] == "CONNECTED"),
            "not_configured": sum(1 for i in integrations if i["status"] == "NOT_CONFIGURED"),
        },
    }


# --- Authentication & RBAC ---

@app.post("/auth/login", responses={401: {"description": "Invalid credentials"}})
def login(payload: LoginPayload, session: Session = Depends(get_session)) -> dict[str, Any]:
    clean_email = payload.email.strip().lower()
    clean_password = payload.password.strip()
    now = utc_now()
    attempts = [item for item in _login_attempts.get(clean_email, []) if item > now - timedelta(minutes=15)]
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    user = session.scalar(select(User).where(User.email == clean_email))
    if not user or not verify_password(clean_password, user.password_hash):
        _login_attempts[clean_email] = attempts + [now]
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _login_attempts.pop(clean_email, None)
    token = issue_token(user, session)
    session.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "organization_id": user.organization_id,
        },
    }


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, session: Session = Depends(get_session), _user: User = Depends(current_user)) -> None:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        revoke_token(authorization[7:], session)
        session.commit()


# --- Webhook Pipeline (Canonical Razorpay Ingestion) ---

@app.post(
    "/webhooks/razorpay",
    responses={
        400: {"description": "Invalid webhook JSON or body shape"},
        401: {"description": "Missing or invalid signature"},
        422: {"description": "No customer available for event"},
    },
)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Annotated[str | None, Header()] = None,
    x_razorpay_account_id: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    payload = await request.body()
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")

    # Account identity is selected before signature validation.  This prevents
    # a valid merchant A signature from ever being applied to merchant B.
    account_id = x_razorpay_account_id or body.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="Razorpay account id required")
    org = session.scalar(select(Organization).where(Organization.razorpay_account_id == account_id))
    if not org:
        raise HTTPException(status_code=404, detail="Unknown Razorpay merchant account")
    secret = org.webhook_secret or settings.RAZORPAY_WEBHOOK_SECRET
    if not secret or not x_razorpay_signature:
        raise HTTPException(status_code=401, detail="Webhook signature required")
    digest = hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()
    if not hmac.compare_digest(digest, x_razorpay_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Prefer Razorpay's event identity. Legacy envelopes use the provider
    # entity id as a stable compatibility key when no envelope id is present.
    provider_event_id = body.get("id") or body.get("event_id")
    if not provider_event_id:
        event_payload = body.get("payload") or {}
        for entity_type in ("payment", "payment_link", "invoice", "subscription", "checkout"):
            entity = (event_payload.get(entity_type) or {}).get("entity") or {}
            if entity.get("id"):
                provider_event_id = f"legacy:{body.get('event', 'unknown')}:{entity['id']}"
                break
    if not isinstance(provider_event_id, str) or not provider_event_id.strip():
        raise HTTPException(status_code=400, detail="Webhook event id required")

    dedupe_key = f"razorpay:event:{provider_event_id}"

    receipt = session.scalar(
        select(WebhookReceipt).where(
            WebhookReceipt.organization_id == org.id,
            WebhookReceipt.provider_event_id == provider_event_id,
        )
    )
    if receipt and receipt.revenue_event_id:
        event = session.get(RevenueEvent, receipt.revenue_event_id)
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.revenue_event_id == receipt.revenue_event_id))
        return {
            "accepted": True,
            "duplicate": True,
            "dedupe_key": receipt.dedupe_key,
            "normalized": event is not None,
            "event_id": event.id if event else receipt.revenue_event_id,
            "case_id": case.id if case else None,
            "case_status": case.status if case else None,
            "recovered_amount": case.recovered_amount if case else 0,
        }
    if not receipt:
        receipt = WebhookReceipt(
            organization_id=org.id,
            provider_event_id=provider_event_id,
            dedupe_key=dedupe_key,
            raw_payload=body,
        )
        session.add(receipt)
        session.flush()

    # Locate Customer
    customer = None
    customer_id = body.get("customer_id")
    if not customer_id and "payload" in body:
        for entity_type in ("payment", "payment_link", "invoice", "subscription"):
            if entity_type in body["payload"]:
                ent = body["payload"][entity_type].get("entity", {})
                customer_id = ent.get("customer_id") or ent.get("notes", {}).get("customer_id")
                if customer_id:
                    break

    if customer_id:
        customer = session.scalar(
            select(Customer).where(
                Customer.organization_id == org.id,
                (Customer.id == customer_id) | (Customer.razorpay_customer_id == customer_id),
            )
        )
    if not customer:
        receipt.status = "REJECTED"
        receipt.rejection_reason = "No customer available for event"
        session.commit()
        raise HTTPException(status_code=422, detail="No customer available for event")

    try:
        event, case, is_duplicate = CaseService.process_event(
            session=session,
            org=org,
            customer=customer,
            raw_body=body,
            dedupe_key=dedupe_key,
            actor="razorpay_webhook",
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    receipt.status = "PROCESSED"
    receipt.revenue_event_id = event.id
    receipt.processed_at = datetime.now(timezone.utc)
    session.commit()

    return {
        "accepted": True,
        "duplicate": is_duplicate,
        "dedupe_key": dedupe_key,
        "normalized": True,
        "event_id": event.id,
        "case_id": case.id if case else None,
        "case_status": case.status if case else None,
        "recovered_amount": case.recovered_amount if case else 0,
    }


# --- Recovery Cases & Investigation ---

@app.get("/recovery-cases")
def list_cases(
    status: str | None = None,
    risk: str | None = None,
    revenue_type: str | None = None,
    query: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = select(RecoveryCase).where(RecoveryCase.organization_id == user.organization_id).order_by(desc(RecoveryCase.created_at))
    if status and status.upper() != "ALL":
        stmt = stmt.where(RecoveryCase.status == status.upper())

    cases = list(session.scalars(stmt).all())

    # In-memory filtering for risk tier & revenue type & text query
    if risk and risk.upper() != "ALL":
        cases = [
            c for c in cases
            if (risk.upper() == "HIGH" and c.risk_assessment and c.risk_assessment.risk_score >= 75)
            or (risk.upper() == "MEDIUM" and c.risk_assessment and 50 <= c.risk_assessment.risk_score < 75)
            or (risk.upper() == "LOW" and c.risk_assessment and c.risk_assessment.risk_score < 50)
        ]

    if revenue_type and revenue_type.upper() != "ALL":
        cases = [c for c in cases if c.revenue_event and c.revenue_event.event_type == revenue_type.upper()]

    if query:
        q = query.lower()
        cases = [
            c for c in cases
            if (c.customer and q in c.customer.name.lower()) or q in c.id.lower()
        ]

    # Prioritize by expected recovery value descending (RecoverX differentiator)
    cases.sort(
        key=lambda c: c.risk_assessment.expected_recovery_value if c.risk_assessment else 0,
        reverse=True,
    )

    page_limit = max(1, min(limit, 500))
    return {
        "items": [serialize_case(c) for c in cases[:page_limit]],
        "total": len(cases),
    }


@app.get("/recovery-cases/{case_id}", responses={404: {"description": "Case not found"}})
def get_case(case_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict[str, Any]:
    case = session.scalar(
        select(RecoveryCase).where(
            RecoveryCase.id == case_id,
            RecoveryCase.organization_id == user.organization_id,
        )
    )
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    decision = session.scalar(
        select(AgentDecision).where(AgentDecision.recovery_case_id == case.id).order_by(desc(AgentDecision.created_at))
    )
    link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case.id))
    latest_link_action = session.scalar(
        select(RecoveryAction)
        .where(
            RecoveryAction.recovery_case_id == case.id,
            RecoveryAction.payload["payment_url"].is_not(None),
        )
        .order_by(desc(RecoveryAction.created_at))
    )
    comms = session.scalars(select(Communication).where(Communication.case_id == case.id)).all()
    escalation = session.scalar(select(Escalation).where(Escalation.case_id == case.id))
    promises = session.scalars(select(PromiseToPay).where(PromiseToPay.case_id == case.id)).all()

    serialized = serialize_case(case)
    serialized.update({
        "diagnosis": decision.diagnosis if decision else "Payment issue diagnosed",
        "root_cause": decision.root_cause if decision else case.failure_reason or "PAYMENT_METHOD_DECLINE",
        "ai_reasoning": decision.reasoning if decision else "Autonomous recovery intervention",
        "payment_link": {
            "id": link.id,
            "provider_link_id": link.provider_link_id,
            "amount": link.amount,
            "status": link.status,
            "short_url": link.short_url,
            "payment_url": (latest_link_action.payload or {}).get("payment_url") if latest_link_action else None,
        } if link else None,
        "communications": [
            {
                "id": m.id,
                "channel": m.channel,
                "direction": m.direction,
                "content": m.content,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m in comms
        ],
        "escalation": {
            "id": escalation.id,
            "reason": escalation.reason,
            "resolution": escalation.resolution,
            "resolution_notes": escalation.resolution_notes,
        } if escalation else None,
        "promises_to_pay": [
            {
                "id": p.id,
                "amount": p.amount,
                "promised_date": p.promised_date.isoformat(),
                "status": p.status,
                "fulfilled": p.fulfilled,
            }
            for p in promises
        ],
    })
    return serialized


@app.post("/recovery-cases/{case_id}/execute")
def execute_case(
    case_id: str,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id, RecoveryCase.organization_id == _user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    try:
        action = default_gateway.execute_recovery_action(
            session=session,
            case=case,
            action_type=case.recommended_action,
            actor=_user.email,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return {"case_id": case_id, "status": "EXECUTED", "action_id": action.id}


@app.post("/recovery-cases/{case_id}/stop")
def stop_case(
    case_id: str,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, str]:
    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id, RecoveryCase.organization_id == _user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    case.status = "STOPPED"
    session.add(
        AuditEvent(
            id=str(uuid4()),
            organization_id=case.organization_id,
            case_id=case.id,
            actor=_user.email,
            event_name="workflow.stopped",
            payload={"reason": "Operator manually stopped case"},
        )
    )
    session.commit()
    return {"case_id": case_id, "status": "STOPPED"}


@app.get("/recovery-cases/{case_id}/payment-link", responses={404: {"description": "Case or payment link not found"}})
def get_payment_link_token(
    case_id: str,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    """Get the payment link token for a case (authenticated users only).
    
    Returns the opaque payment link token that should be shared with the customer.
    Token is valid for PAYMENT_LINK_TTL_HOURS (default 72 hours).
    """
    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id, RecoveryCase.organization_id == _user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    
    link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case.id))
    if not link:
        raise HTTPException(status_code=404, detail="No payment link found for this case")
    
    if link.status in ("PAID", "CANCELLED", "EXPIRED"):
        raise HTTPException(status_code=409, detail=f"Payment link is in terminal state: {link.status}")
    
    if _ensure_aware(link.expires_at) and _ensure_aware(link.expires_at) <= utc_now():
        link.status = "EXPIRED"
        session.commit()
        raise HTTPException(status_code=410, detail="Payment link has expired")
    
    return {
        "case_id": case.id,
        "payment_link_id": link.id,
        "amount": link.amount,
        "currency": case.currency,
        "status": link.status,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        # Note: We never return the unhashed token in responses - it's only available at creation time
        # The customer receives the token via SMS/email during recovery action execution
        "payment_url": f"/pay/{{token}}" if link.public_token_hash else None,
    }


# --- Human Escalation Queue ---

@app.get("/escalations")
def list_escalations(session: Session = Depends(get_session), _user: User = Depends(current_user)) -> dict[str, Any]:
    cases = session.scalars(select(RecoveryCase).where(RecoveryCase.status == "ESCALATED", RecoveryCase.organization_id == _user.organization_id)).all()
    return {
        "items": [serialize_case(c) for c in cases],
        "total": len(cases),
    }


@app.post("/recovery-cases/{case_id}/approve")
@app.post("/escalations/{case_id}/resolve")
def resolve_escalation(
    case_id: str,
    payload: ResolutionPayload,
    session: Session = Depends(get_session),
    user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER")),
) -> dict[str, Any]:
    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id, RecoveryCase.organization_id == user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    escalation = session.scalar(select(Escalation).where(Escalation.case_id == case.id))
    if not escalation:
        escalation = default_gateway.create_escalation(
            session=session,
            case_id=case.id,
            reason=case.policy_decision or "HUMAN_REVIEW",
            assigned_to_user_id=user.id,
            actor=user.email,
        )

    escalation.resolution = payload.resolution
    escalation.resolution_notes = payload.notes

    if payload.resolution.upper() in ("APPROVE", "EDIT", "CONTACT"):
        case.status = "WAITING_FOR_PAYMENT"
        try:
            default_gateway.execute_recovery_action(
                session=session,
                case=case,
                action_type=case.recommended_action,
                actor=user.email,
                human_approved_by=user.email,
            )
            workflow_runner.trigger_recovery_workflow(session, case.id)
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        case.status = "STOPPED"

    session.add(
        AuditEvent(
            id=str(uuid4()),
            organization_id=user.organization_id,
            case_id=case.id,
            actor=user.email,
            event_name="escalation.resolved",
            payload={"resolution": payload.resolution, "notes": payload.notes},
        )
    )
    session.commit()
    return {"case_id": case.id, "resolution": escalation.resolution, "status": case.status}


# --- Policy Management ---

@app.get("/policies")
def get_policy(session: Session = Depends(get_session), user: User = Depends(current_user)) -> PolicyPayload:
    org = get_org(session, user.organization_id)
    policy = CaseService.get_or_create_policy(session, org.id)
    return PolicyPayload.model_validate(policy, from_attributes=True)


@app.put("/policies")
def update_policy(
    payload: PolicyPayload,
    session: Session = Depends(get_session),
    user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER")),
) -> PolicyPayload:
    org = get_org(session, user.organization_id)
    policy = CaseService.get_or_create_policy(session, org.id)
    for key, value in payload.model_dump().items():
        setattr(policy, key, value)
    policy.updated_by = user.email
    policy.updated_at = datetime.now(timezone.utc)

    session.add(
        AuditEvent(
            id=str(uuid4()),
            organization_id=org.id,
            actor=user.email,
            event_name="policy.updated",
            payload=payload.model_dump(),
        )
    )
    session.commit()
    return payload


# --- Real-Time Analytics ---

@app.get("/analytics/recovery")
def analytics(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    return AnalyticsService.get_recovery_analytics(session, user.organization_id)


@app.get("/analytics/strategy-performance")
def strategy_performance(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    return AnalyticsService.get_strategy_performance(session, user.organization_id)


@app.get("/analytics/experiments")
def experiments(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    return AnalyticsService.get_experiments(session, user.organization_id)


# --- Audit Trail ---

@app.get("/audit-events")
def audit_events(
    limit: int = 50,
    case_id: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    stmt = select(AuditEvent).where(AuditEvent.organization_id == user.organization_id).order_by(desc(AuditEvent.created_at))
    if case_id:
        stmt = stmt.where(AuditEvent.case_id == case_id)
    events = session.scalars(stmt.limit(min(limit, 200))).all()
    return {
        "items": [
            {
                "id": e.id,
                "event_name": e.event_name,
                "case_id": e.case_id,
                "actor": e.actor,
                "payload": e.payload,
                "correlation_id": e.correlation_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "total": len(events),
    }


# --- Customers & Payments ---

@app.get("/customers")
def list_customers(limit: int = 50, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict[str, Any]:
    customers = session.scalars(select(Customer).where(Customer.organization_id == user.organization_id).order_by(desc(Customer.lifetime_value)).limit(limit)).all()
    return {"items": [serialize_customer(c) for c in customers], "total": len(customers)}


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict[str, Any]:
    customer = session.scalar(select(Customer).where(Customer.id == customer_id, Customer.organization_id == user.organization_id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return serialize_customer(customer)


# --- Simulation Center & Customer Simulator ---

@app.post("/simulation/payment")
def simulate_customer_payment(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    """Customer Simulator: Customer clicks [Pay Now].
    Triggers simulated payment capture, emits canonical webhook, marks case RECOVERED, and updates dashboard.
    """
    if not request.case_id:
        raise HTTPException(status_code=400, detail="case_id is required")

    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == request.case_id, RecoveryCase.organization_id == _user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    customer = session.get(Customer, case.customer_id)
    if not customer:
        raise HTTPException(status_code=409, detail="Customer record missing for payment case")
    org = get_org(session, _user.organization_id)

    # Simulated Razorpay emits payment_link.paid / payment.captured
    provider = SimulatedRazorpayProvider()
    link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case.id))

    webhook_payload = provider.generate_webhook(
        event_type="payment_link.paid" if link else "payment.captured",
        entity_data={
            "id": link.provider_link_id if link else f"pay_{case.id}",
            "amount": case.amount,
            "currency": "INR",
            "status": "paid" if link else "captured",
            "notes": {"case_id": case.id, "customer_id": customer.id if customer else "cus_default"},
        },
    )

    _process_simulated_webhook(
        session=session,
        org=org,
        customer=customer,
        webhook_payload=webhook_payload,
        actor="customer_simulator",
    )
    session.commit()

    return {
        "case_id": case.id,
        "status": case.status,
        "recovered_amount": case.recovered_amount,
        "message": f"Successfully captured {case.currency} {case.recovered_amount:,}. Case marked RECOVERED.",
    }


@app.post("/simulation/failure")
def simulate_failure(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    """Simulates a provider timeout or retry safely without duplicating actions."""
    if not request.case_id:
        raise HTTPException(status_code=400, detail="case_id is required")
    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == request.case_id, RecoveryCase.organization_id == _user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    session.add(
        AuditEvent(
            id=str(uuid4()),
            organization_id=case.organization_id,
            case_id=case.id,
            actor=_user.email,
            event_name="workflow.retried",
            payload={"provider": "simulated_razorpay", "status": "RETRY_SCHEDULED"},
        )
    )
    session.commit()
    return {"case_id": case.id, "status": "RETRY_SCHEDULED", "workflow_preserved": True}


@app.post("/simulation/timeout")
def simulate_timeout(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    return simulate_failure(request, session, _user)


@app.post("/simulation/opt-out")
def simulate_opt_out(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    """Opt a customer out of all recovery communications.
    Accepts either customer_id or case_id.
    """
    customer_id_raw = request.customer_id or request.case_id
    customer = None
    case_stopped_count = 0

    if request.customer_id:
        customer = session.scalar(
            select(Customer).where(
                Customer.organization_id == _user.organization_id,
                (Customer.id == request.customer_id) | (Customer.razorpay_customer_id == request.customer_id),
            )
        )
    elif request.case_id:
        case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == request.case_id, RecoveryCase.organization_id == _user.organization_id))
        if case:
            customer = session.get(Customer, case.customer_id)

    if not customer and customer_id_raw:
        customer = session.scalar(
            select(Customer).where(
                Customer.organization_id == _user.organization_id,
                (Customer.id == customer_id_raw) | (Customer.razorpay_customer_id == customer_id_raw),
            )
        )

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    customer.opted_out = True
    # Stop all active cases for this customer
    active_cases = session.scalars(
        select(RecoveryCase).where(
            RecoveryCase.customer_id == customer.id,
            RecoveryCase.organization_id == _user.organization_id,
            RecoveryCase.status.in_(("NEW", "ANALYZING", "ACTIONABLE", "ACTION_PENDING", "ACTION_EXECUTED", "WAITING_FOR_PAYMENT", "PROMISE_TO_PAY")),
        )
    ).all()
    for c in active_cases:
        c.status = "STOPPED"
        case_stopped_count += 1
        session.add(AuditEvent(
            id=str(uuid4()),
            organization_id=c.organization_id,
            case_id=c.id,
            actor=_user.email,
            event_name="customer.opted_out",
            payload={"customer_id": customer.id},
        ))
    session.commit()
    return {"customer_id": customer.id, "opted_out": True, "cases_stopped": case_stopped_count}


def _ensure_simulation_escalation(session: Session, case: RecoveryCase, reason: str, actor: str) -> Escalation:
    escalation = session.scalar(select(Escalation).where(Escalation.case_id == case.id))
    if not escalation:
        escalation = Escalation(id=str(uuid4()), case_id=case.id, reason=reason)
        session.add(escalation)
    session.add(AuditEvent(
        id=str(uuid4()),
        organization_id=case.organization_id,
        case_id=case.id,
        actor=actor,
        event_name="failure_lab.escalated",
        payload={"reason": reason},
    ))
    return escalation


@app.post("/simulation/low-confidence")
def simulate_low_confidence(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    if not request.case_id:
        raise HTTPException(status_code=400, detail="case_id is required")
    case = session.scalar(select(RecoveryCase).where(
        RecoveryCase.id == request.case_id,
        RecoveryCase.organization_id == _user.organization_id,
    ))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    policy = CaseService.get_or_create_policy(session, case.organization_id)
    case.ai_confidence = max(0.0, policy.min_ai_confidence - 0.20)
    case.policy_decision = "HUMAN_REVIEW"
    case.status = "ESCALATED"
    _ensure_simulation_escalation(session, case, "LOW_CONFIDENCE", _user.email)
    session.commit()
    return {"case_id": case.id, "status": case.status, "ai_confidence": case.ai_confidence}


@app.post("/simulation/max-attempts")
def simulate_max_attempts(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    if not request.case_id:
        raise HTTPException(status_code=400, detail="case_id is required")
    case = session.scalar(select(RecoveryCase).where(
        RecoveryCase.id == request.case_id,
        RecoveryCase.organization_id == _user.organization_id,
    ))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    policy = CaseService.get_or_create_policy(session, case.organization_id)
    case.contact_attempts = policy.max_contact_attempts
    case.policy_decision = "STOP"
    case.status = "STOPPED"
    session.add(AuditEvent(
        id=str(uuid4()),
        organization_id=case.organization_id,
        case_id=case.id,
        actor=_user.email,
        event_name="failure_lab.max_attempts_reached",
        payload={"contact_attempts": case.contact_attempts},
    ))
    session.commit()
    return {"case_id": case.id, "status": case.status, "contact_attempts": case.contact_attempts}


@app.post("/simulation/invalid-ai")
def simulate_invalid_ai(
    request: SimulationRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    if not request.case_id:
        raise HTTPException(status_code=400, detail="case_id is required")
    case = session.scalar(select(RecoveryCase).where(
        RecoveryCase.id == request.case_id,
        RecoveryCase.organization_id == _user.organization_id,
    ))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    if case.status in ("RECOVERED", "STOPPED", "EXPIRED"):
        raise HTTPException(status_code=409, detail=f"Case is already terminal: {case.status}")
    case.policy_decision = "HUMAN_REVIEW"
    case.status = "ESCALATED"
    case.failure_reason = "invalid_ai_response"
    _ensure_simulation_escalation(session, case, "SPECIAL_CASE", _user.email)
    session.add(AuditEvent(
        id=str(uuid4()),
        organization_id=case.organization_id,
        case_id=case.id,
        actor=_user.email,
        event_name="ai.invalid_output_safe_failure",
        payload={"fallback": "HUMAN_REVIEW"},
    ))
    session.commit()
    return {"case_id": case.id, "status": case.status, "fallback": "HUMAN_REVIEW"}


# --- Public Customer Payment Simulator (no auth required) ---

def _public_payment_link(token: str, session: Session) -> tuple[PaymentLink, RecoveryCase]:
    link = session.scalar(select(PaymentLink).where(PaymentLink.public_token_hash == sha256(token.encode()).hexdigest()))
    expires_at = _ensure_aware(link.expires_at) if link else None
    if not link or link.status in ("PAID", "CANCELLED", "EXPIRED") or (expires_at and expires_at <= utc_now()):
        if link and expires_at and expires_at <= utc_now():
            link.status = "EXPIRED"
            session.commit()
        raise HTTPException(status_code=404, detail="Payment link is invalid or expired")
    case = session.get(RecoveryCase, link.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Payment request not found")
    return link, case


@app.get("/pay/{token}")
def get_payment_request(token: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Public endpoint: returns payment request details for the customer-facing pay page.
    No authentication required — the case ID is the access token for this flow.
    """
    link, case = _public_payment_link(token, session)
    customer = session.get(Customer, case.customer_id)
    event = case.revenue_event
    return {
        "case_id": case.id,
        "customer_name": customer.name if customer else "Customer",
        "customer_email": customer.email if customer else "",
        "amount": case.amount,
        "currency": case.currency,
        "status": case.status,
        "recovered_amount": case.recovered_amount,
        "event_type": event.event_type if event else "PAYMENT_FAILURE",
        "failure_reason": case.failure_reason or "Payment could not be processed",
        "recommended_action": case.recommended_action,
        "payment_link": {
            "id": link.id,
            "short_url": link.short_url,
            "amount": link.amount,
            "status": link.status,
        } if link else None,
    }


class CustomerPayRequest(BaseModel):
    """Customer-submitted payment request."""
    action: str = "pay"  # "pay" or "promise"
    promise_date: str | None = None


@app.post("/pay/{token}")
def submit_customer_payment(
    token: str,
    body: CustomerPayRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Public endpoint: customer clicks [Pay Now] or [Promise to Pay] on the payment page.
    Routes through the full RecoverX pipeline — signed simulated webhook → RECOVERED.
    """
    link, case = _public_payment_link(token, session)
    if case.status in ("RECOVERED", "STOPPED", "EXPIRED"):
        raise HTTPException(status_code=409, detail=f"Case is already in terminal state: {case.status}")

    customer = session.get(Customer, case.customer_id)
    if not customer:
        raise HTTPException(status_code=409, detail="Customer record missing for payment case")
    org = get_org(session, case.organization_id)

    if body.action == "promise":
        from datetime import date
        promise_date_str = body.promise_date or (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        promise_dt = datetime.fromisoformat(promise_date_str + "T00:00:00+00:00") if "T" not in promise_date_str else datetime.fromisoformat(promise_date_str)
        promise = PromiseToPay(
            id=str(uuid4()),
            case_id=case.id,
            customer_id=case.customer_id,
            amount=case.amount,
            promised_date=promise_dt,
            status="PENDING",
        )
        case.status = "PROMISE_TO_PAY"
        session.add(promise)
        session.add(AuditEvent(
            id=str(uuid4()),
            organization_id=org.id,
            case_id=case.id,
            actor="customer_self_service",
            event_name="promise.created",
            payload={"amount": case.amount, "promised_date": promise_date_str},
        ))
        session.commit()
        return {"case_id": case.id, "status": "PROMISE_TO_PAY", "promise_id": promise.id, "promised_date": promise_date_str}

    # action == "pay": emit simulated payment webhook through RecoverX pipeline
    provider = SimulatedRazorpayProvider()
    webhook_payload = provider.generate_webhook(
        event_type="payment_link.paid" if link else "payment.captured",
        entity_data={
            "id": link.provider_link_id if link else f"pay_{case.id}",
            "amount": case.amount,
            "currency": "INR",
            "status": "paid" if link else "captured",
            "notes": {"case_id": case.id, "customer_id": customer.id if customer else "cus_default"},
        },
    )
    _process_simulated_webhook(
        session=session,
        org=org,
        customer=customer,
        webhook_payload=webhook_payload,
        actor="customer_self_service",
    )
    session.commit()
    return {
        "case_id": case.id,
        "status": case.status,
        "recovered_amount": case.recovered_amount,
        "message": f"Payment captured. Case status: {case.status}",
    }



@app.post("/simulation/promise-to-pay")
def create_promise(
    payload: PromisePayload,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    case = session.scalar(select(RecoveryCase).where(RecoveryCase.id == payload.case_id, RecoveryCase.organization_id == _user.organization_id))
    if not case:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    promise = default_gateway.record_promise_to_pay(
        session=session,
        case_id=case.id,
        amount=payload.amount,
        promised_date=payload.promised_date,
        notes=payload.notes,
        actor=_user.email,
    )
    session.commit()
    return {
        "id": promise.id,
        "case_id": case.id,
        "amount": promise.amount,
        "promised_date": promise.promised_date.isoformat(),
        "status": promise.status,
    }


@app.post("/simulation/promise-to-pay/{promise_id}/fulfill")
def fulfill_promise(
    promise_id: str,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    promise = session.scalar(
        select(PromiseToPay)
        .join(RecoveryCase, RecoveryCase.id == PromiseToPay.case_id)
        .where(
            PromiseToPay.id == promise_id,
            RecoveryCase.organization_id == _user.organization_id,
        )
    )
    if not promise:
        raise HTTPException(status_code=404, detail="Promise not found")
    res = workflow_runner.trigger_promise_workflow(session, promise_id)
    session.commit()
    return res


@app.post("/simulation/event")
def simulate_event(
    payload: EventPayload,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER", "OPERATOR")),
) -> dict[str, Any]:
    org = get_org(session, _user.organization_id)
    customer = None
    if payload.customer_id:
        customer = session.scalar(
            select(Customer).where(
                Customer.organization_id == org.id,
                (Customer.id == payload.customer_id) | (Customer.razorpay_customer_id == payload.customer_id),
            )
        )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found for this organization")
    if not customer:
        raise HTTPException(status_code=404, detail="No customer found")

    provider = SimulatedRazorpayProvider()
    event_id = payload.id or f"sim_{uuid4().hex[:10]}"
    simulated_event_names = {
        "PAYMENT_FAILURE": "payment.failed",
        "PAYMENT_CAPTURED": "payment.captured",
        "PAYMENT_LINK_PAID": "payment_link.paid",
        "PAYMENT_LINK_ABANDONED": "payment_link.abandoned",
        "INVOICE_OVERDUE": "invoice.overdue",
        "INVOICE_PAID": "invoice.paid",
        "SUBSCRIPTION_HALTED": "subscription.halted",
        "SUBSCRIPTION_CHARGED": "subscription.charged",
        "CHECKOUT_ABANDONED": "checkout.abandoned",
    }
    provider_event_name = simulated_event_names.get(payload.event_type, payload.event_type)
    webhook_payload = provider.generate_webhook(
        event_type=provider_event_name,
        entity_data={
            "id": event_id,
            "customer_id": customer.razorpay_customer_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "notes": {"customer_id": customer.razorpay_customer_id},
        },
        event_id=event_id,
    )
    event, case, is_duplicate = _process_simulated_webhook(
        session=session,
        org=org,
        customer=customer,
        webhook_payload=webhook_payload,
        actor=_user.email,
    )
    session.commit()
    return {
        "event_id": event.id,
        "case_id": case.id if case else None,
        "event_type": event.event_type,
        "status": case.status if case else None,
        "is_duplicate": is_duplicate,
    }


# --- Model Context Protocol (MCP) Interface ---

@app.get("/mcp/tools")
def list_mcp_tools(_user: User = Depends(current_user)) -> list[dict[str, Any]]:
    return mcp_server.list_tools()


@app.post("/mcp")
def execute_mcp_tool(
    request: MCPRequest,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    try:
        res = mcp_server.call_tool(
            session,
            request.tool,
            request.arguments,
            actor=user.email,
            organization_id=user.organization_id,
        )
        session.commit()
        return {"tool": request.tool, "result": res}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# --- Batch & Demo Seeding ---

@app.post("/demo/seed")
@app.post("/demo/reset")
def seed_demo(
    request: BatchRequest = BatchRequest(),
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN")),
) -> dict[str, Any]:
    res = generate_synthetic_dataset(
        session=session,
        customer_count=request.customers,
        case_count=request.cases,
        seed=request.seed,
    )
    return res


@app.post("/demo/run-batch")
def run_batch(
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles("ADMIN", "FINANCE_MANAGER")),
) -> dict[str, Any]:
    return EvaluationService.run_evaluation(session, _user.organization_id)
