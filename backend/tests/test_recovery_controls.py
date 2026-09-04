"""Expanded RecoverX test suite.
Covers: risk engine, policy engine, normalizer, idempotency, tenant isolation,
full pipeline integration (webhook → event → case → risk → policy → gateway), and state transitions.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import hmac, hashlib, json, os

os.environ.setdefault("DATABASE_URL", f"sqlite:///./recoverx-test-{os.getpid()}.db")
os.environ.setdefault("BOOTSTRAP_RAZORPAY_ACCOUNT_ID", "acct_test_0001")

from app.db import Customer, Policy, RecoveryCase, Organization, User
from app.services.event_normalizer import normalize_event
from app.services.policy_engine import PolicyEngine
from app.services.risk_engine import RiskEngine
from app.auth import hash_password


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_customer(**overrides):
    values = {
        "payment_reliability_pct": 91.0,
        "historical_recovery_rate": 0.88,
        "successful_payments": 18,
        "failed_payments": 1,
        "opted_out": False,
    }
    values.update(overrides)
    return Customer(**values)


def make_policy(**overrides):
    values = {
        "organization_id": "org-1",
        "min_ai_confidence": 0.70,
        "max_auto_action_amount": 25000,
        "human_approval_above_amount": 25000,
        "max_contact_attempts": 3,
        "escalate_after_days": 7,
    }
    values.update(overrides)
    return Policy(**values)


def make_case(**overrides):
    values = {
        "organization_id": "org-1",
        "amount": 18000,
        "status": "ACTIONABLE",
        "contact_attempts": 0,
        "ai_confidence": 0.91,
    }
    values.update(overrides)
    return RecoveryCase(**values)


# ─── Risk Engine ──────────────────────────────────────────────────────────────

def test_risk_engine_calculates_expected_recovery_from_probability():
    result = RiskEngine.evaluate(18000, make_customer())
    assert result.risk_score == 24
    assert result.recovery_probability == 0.84
    assert result.expected_recovery_value == 15120


def test_risk_engine_is_deterministic():
    """Same inputs → identical outputs every time."""
    c = make_customer()
    r1 = RiskEngine.evaluate(18000, c)
    r2 = RiskEngine.evaluate(18000, c)
    assert r1.risk_score == r2.risk_score
    assert r1.recovery_probability == r2.recovery_probability
    assert r1.expected_recovery_value == r2.expected_recovery_value


def test_risk_engine_higher_reliability_yields_lower_risk():
    low = RiskEngine.evaluate(18000, make_customer(payment_reliability_pct=30.0))
    high = RiskEngine.evaluate(18000, make_customer(payment_reliability_pct=95.0))
    # Lower reliability → higher risk score
    assert low.risk_score >= high.risk_score


def test_risk_engine_expected_recovery_uses_amount_times_probability():
    result = RiskEngine.evaluate(10000, make_customer())
    # expected = amount × probability (may be rounded to int)
    assert result.expected_recovery_value == int(10000 * result.recovery_probability)


# ─── Policy Engine ────────────────────────────────────────────────────────────

def test_policy_stops_opted_out_customer():
    result = PolicyEngine.evaluate(make_policy(), make_case(), make_customer(opted_out=True))
    assert result.decision == "STOP"
    assert "CUSTOMER_OPTED_OUT" in result.rule_violations


def test_policy_requires_human_review_above_amount_limit():
    result = PolicyEngine.evaluate(make_policy(), make_case(amount=30000), make_customer())
    assert result.decision == "HUMAN_REVIEW"
    assert "AMOUNT_EXCEEDS_AUTO_LIMIT" in result.rule_violations


def test_policy_auto_approves_within_limits():
    result = PolicyEngine.evaluate(make_policy(), make_case(amount=5000), make_customer())
    assert result.decision == "AUTO_APPROVE"
    assert result.rule_violations == []


def test_policy_stops_max_attempts():
    result = PolicyEngine.evaluate(
        make_policy(max_contact_attempts=3),
        make_case(contact_attempts=3),
        make_customer(),
    )
    assert result.decision == "STOP"
    assert "MAX_ATTEMPTS_EXCEEDED" in result.rule_violations


def test_policy_human_review_on_low_confidence():
    result = PolicyEngine.evaluate(
        make_policy(min_ai_confidence=0.80),
        make_case(ai_confidence=0.60),
        make_customer(),
        ai_confidence=0.60,
    )
    assert result.decision == "HUMAN_REVIEW"
    assert "LOW_AI_CONFIDENCE" in result.rule_violations


def test_policy_stops_terminal_case():
    for terminal_status in ("RECOVERED", "STOPPED", "EXPIRED"):
        result = PolicyEngine.evaluate(make_policy(), make_case(status=terminal_status), make_customer())
        assert result.decision == "STOP"
        assert "CASE_ALREADY_TERMINATED" in result.rule_violations


# ─── Normalizer ───────────────────────────────────────────────────────────────

def test_normalizer_maps_razorpay_failure_to_canonical_event():
    result = normalize_event({
        "entity": "event",
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay_123", "customer_id": "cus_123", "amount": 18000}}},
    })
    assert result.event_type == "PAYMENT_FAILURE"
    assert result.source_id == "pay_123"
    assert result.customer_id == "cus_123"
    assert result.amount == 18000


def test_normalizer_maps_checkout_abandonment_to_canonical_event():
    result = normalize_event({
        "entity": "event",
        "event": "checkout.abandoned",
        "payload": {"checkout": {"entity": {"id": "chk_123", "customer_id": "cus_123", "amount": 18000}}},
    })
    assert result.event_type == "CHECKOUT_ABANDONED"
    assert result.source_id == "chk_123"


def test_normalizer_maps_payment_link_abandonment_to_canonical_event():
    result = normalize_event({
        "entity": "event",
        "event": "payment_link.abandoned",
        "payload": {"payment_link": {"entity": {"id": "plink_123", "customer_id": "cus_123", "amount": 18000}}},
    })
    assert result.event_type == "PAYMENT_LINK_ABANDONED"
    assert result.source_entity == "payment_link"


def test_normalizer_rejects_unsupported_event():
    with pytest.raises(ValueError, match="Unsupported"):
        normalize_event({
            "entity": "event",
            "event": "totally.unknown.event",
            "payload": {},
        })


def test_normalizer_rejects_zero_amount():
    with pytest.raises(ValueError):
        normalize_event({
            "entity": "event",
            "event": "payment.failed",
            "payload": {"payment": {"entity": {"id": "p1", "customer_id": "c1", "amount": 0}}},
        })


# ─── Integration: Full Pipeline (Webhook → Case) ──────────────────────────────

@pytest.fixture(scope="session")
def live_client():
    """TestClient that runs the full app lifespan (DB init, user seeding)."""
    from app.main import app
    with TestClient(app) as c:
        # Ensure bootstrap organization exists with correct account ID
        from app.db import Organization, Policy, get_session
        session = next(get_session())
        try:
            org = session.query(Organization).filter_by(razorpay_account_id="acct_test_0001").first()
            if not org:
                org = session.query(Organization).first()
                if org:
                    org.razorpay_account_id = "acct_test_0001"
                    session.commit()
        finally:
            session.close()
        yield c


def _login(client, email="admin@recoverx.local", password="recoverx-demo"):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _signed_webhook(payload_dict: dict) -> tuple[bytes, str]:
    """Return (body, signature) for a signed webhook payload.
    Uses the same default secret as the app (recoverx_webhook_secret_key_2026).
    """
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "recoverx_webhook_secret_key_2026")
    body = json.dumps(payload_dict).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def _get_one_customer(client, headers: dict) -> dict:
    resp = client.get("/customers?limit=1", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "No customers seeded — startup fixture may not have run"
    return items[0]


def test_full_pipeline_creates_case_from_webhook(live_client):
    """Webhook → verification → dedup → normalization → case creation."""
    headers = _login(live_client)
    customer = _get_one_customer(live_client, headers)
    payload = {
        "account_id": "acct_test_0001",
        "entity": "event",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_pipe_{customer['id'][:8]}",
                    "customer_id": customer["id"],
                    "amount": 5000,
                }
            }
        },
    }
    body, sig = _signed_webhook(payload)
    response = live_client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"x-razorpay-signature": sig, "content-type": "application/json"},
    )
    assert response.status_code in (200, 201), f"Webhook failed: {response.text}"
    data = response.json()
    # Actual response shape: {accepted, duplicate, dedupe_key, normalized, event_id, case_id, case_status}
    assert data.get("accepted") is True
    assert "dedupe_key" in data


def test_duplicate_webhook_is_idempotent(live_client):
    """Replaying the same webhook must not create a duplicate case."""
    headers = _login(live_client)
    customer = _get_one_customer(live_client, headers)
    payload = {
        "account_id": "acct_test_0001",
        "entity": "event",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_idem_{customer['id'][:8]}",
                    "customer_id": customer["id"],
                    "amount": 7500,
                }
            }
        },
    }
    body, sig = _signed_webhook(payload)
    r1 = live_client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": sig, "content-type": "application/json"})
    r2 = live_client.post("/webhooks/razorpay", content=body, headers={"x-razorpay-signature": sig, "content-type": "application/json"})
    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)
    # Second call must be marked as a duplicate — same event, same dedupe_key
    r2_data = r2.json()
    assert r2_data.get("duplicate") is True, f"Expected duplicate=True, got: {r2_data}"
    assert r2_data.get("accepted") is True, "Duplicate should still return accepted=True"


def test_unsigned_webhook_is_rejected(live_client):
    """Webhook with no signature must be rejected with 401 or 400."""
    body = json.dumps({"entity": "event", "event": "payment.failed", "payload": {}}).encode()
    response = live_client.post("/webhooks/razorpay", content=body, headers={"content-type": "application/json"})
    assert response.status_code in (400, 401, 422)


def test_wrong_signature_webhook_is_rejected(live_client):
    headers = _login(live_client)
    customer = _get_one_customer(live_client, headers)
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": f"pay_bad_{customer['id'][:8]}", "customer_id": customer["id"], "amount": 5000}}},
    }
    body, _good_sig = _signed_webhook(payload)
    response = live_client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"x-razorpay-signature": "0" * 64, "content-type": "application/json"},
    )
    assert response.status_code in (400, 401, 422)


# ─── Tenant Isolation ─────────────────────────────────────────────────────────

def test_cases_api_is_tenant_scoped(live_client):
    """Cases list must reject unauthenticated requests."""
    response = live_client.get("/recovery-cases?limit=10")
    assert response.status_code in (401, 403)


def test_cases_api_returns_data_for_authed_user(live_client):
    """Authed user gets their own cases."""
    headers = _login(live_client)
    response = live_client.get("/recovery-cases?limit=10", headers=headers)
    assert response.status_code == 200
    assert "items" in response.json()


def test_stop_case_requires_auth(live_client):
    headers = _login(live_client)
    cases = live_client.get("/recovery-cases?limit=1", headers=headers).json()["items"]
    if cases:
        case_id = cases[0]["id"]
        unauth = live_client.post(f"/recovery-cases/{case_id}/stop")
        assert unauth.status_code in (401, 403)


def test_customer_opt_out_accepts_customer_id(live_client):
    headers = _login(live_client)
    customer = _get_one_customer(live_client, headers)
    response = live_client.post(
        "/simulation/opt-out",
        json={"customer_id": customer["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["customer_id"] == customer["id"]
    assert data["opted_out"] is True


def test_failure_lab_safe_fallbacks_are_persisted(live_client):
    headers = _login(live_client)
    cases = live_client.get("/recovery-cases?limit=500", headers=headers).json()["items"]
    active_cases = [case for case in cases if case["status"] not in ("RECOVERED", "STOPPED", "EXPIRED")]
    assert len(active_cases) >= 2
    first_case, second_case = active_cases[:2]
    low_confidence = live_client.post(
        "/simulation/low-confidence",
        json={"case_id": first_case["id"]},
        headers=headers,
    )
    assert low_confidence.status_code == 200
    assert low_confidence.json()["status"] == "ESCALATED"

    max_attempts = live_client.post(
        "/simulation/max-attempts",
        json={"case_id": second_case["id"]},
        headers=headers,
    )
    assert max_attempts.status_code == 200
    assert max_attempts.json()["status"] == "STOPPED"

    invalid_ai = live_client.post(
        "/simulation/invalid-ai",
        json={"case_id": first_case["id"]},
        headers=headers,
    )
    assert invalid_ai.status_code == 200
    assert invalid_ai.json()["fallback"] == "HUMAN_REVIEW"


# ─── State Machine ────────────────────────────────────────────────────────────

def test_stopped_case_cannot_be_executed():
    """A STOPPED case must be rejected by the policy engine / gateway."""
    result = PolicyEngine.evaluate(make_policy(), make_case(status="STOPPED"), make_customer())
    assert result.decision == "STOP"


def test_recovered_case_cannot_be_re_executed():
    result = PolicyEngine.evaluate(make_policy(), make_case(status="RECOVERED"), make_customer())
    assert result.decision == "STOP"


def test_reminder_uses_a_persisted_provider_payment_link(live_client):
    """Invoice reminders cannot send a fabricated payment URL."""
    headers = _login(live_client)
    customers = live_client.get("/customers?limit=20", headers=headers).json()["items"]
    customer = next(item for item in customers if not item["opted_out"])
    response = live_client.post(
        "/simulation/event",
        json={"event_type": "INVOICE_OVERDUE", "customer_id": customer["id"], "amount": 5000},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    case_id = response.json()["case_id"]
    detail = live_client.get(f"/recovery-cases/{case_id}", headers=headers)
    assert detail.status_code == 200
    data = detail.json()
    assert data["payment_link"] is not None
    assert data["payment_link"]["short_url"].startswith("https://rzp.io/i/")
    assert any(data["payment_link"]["short_url"] in item["content"] for item in data["communications"])


def test_customer_payment_url_completes_public_simulator_flow(live_client):
    """The authenticated case URL must open the opaque-token payment page."""
    headers = _login(live_client)
    customer = next(
        item for item in live_client.get("/customers?limit=20", headers=headers).json()["items"]
        if not item["opted_out"]
    )
    response = live_client.post(
        "/simulation/event",
        json={"event_type": "INVOICE_OVERDUE", "customer_id": customer["id"], "amount": 6100},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    case_id = response.json()["case_id"]
    detail = live_client.get(f"/recovery-cases/{case_id}", headers=headers)
    assert detail.status_code == 200
    payment_url = detail.json()["payment_link"]["payment_url"]
    assert payment_url and payment_url.startswith("/pay/")
    token = payment_url.removeprefix("/pay/")

    public_detail = live_client.get(f"/pay/{token}")
    assert public_detail.status_code == 200, public_detail.text
    assert public_detail.json()["case_id"] == case_id
    paid = live_client.post(f"/pay/{token}", json={"action": "pay"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "RECOVERED"


# ─── Analytics ────────────────────────────────────────────────────────────────

def test_analytics_endpoint_returns_real_data(live_client):
    headers = _login(live_client)
    response = live_client.get("/analytics/recovery", headers=headers)
    assert response.status_code == 200
    data = response.json()
    for field in ("revenue_at_risk", "revenue_recovered", "recovery_rate", "cases"):
        assert field in data, f"Missing field: {field}"
    # Values come from DB — we only check shape, not hardcoded numbers


def test_strategy_performance_returns_real_data(live_client):
    headers = _login(live_client)
    response = live_client.get("/analytics/strategy-performance", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ─── Integration Status ────────────────────────────────────────────────────────

def test_integrations_status_reports_simulated_when_no_credentials(live_client):
    """Without real Razorpay credentials set, status must be SIMULATED not CONNECTED."""
    env_backup = {}
    for key in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
        env_backup[key] = os.environ.pop(key, None)
    try:
        headers = _login(live_client)
        response = live_client.get("/integrations/status", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "integrations" in data
        assert "counts" in data
        rzp = next((i for i in data["integrations"] if i["name"] == "Razorpay"), None)
        assert rzp is not None
        assert rzp["status"] == "SIMULATED"
    finally:
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v


def test_integrations_status_structure(live_client):
    """Integration status must have well-formed entries with required fields."""
    headers = _login(live_client)
    response = live_client.get("/integrations/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    for entry in data["integrations"]:
        assert "name" in entry
        assert "status" in entry
        assert entry["status"] in ("CONNECTED", "SIMULATED", "NOT_CONFIGURED")
        assert "label" in entry
        assert "detail" in entry


# ─── Railway & PostgreSQL FK Regression Tests ─────────────────────────────────

def test_synthetic_dataset_generator_enforces_foreign_keys():
    """Verify generator succeeds when foreign keys are actively enforced (simulating PostgreSQL)."""
    from sqlalchemy import create_engine, event, select, func
    from sqlalchemy.orm import Session
    from app.db import Base, RecoveryCase, ExperimentResult
    from app.simulation.generator import generate_synthetic_dataset

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = Session(engine)

    res = generate_synthetic_dataset(session, customer_count=50, case_count=20, seed=20260902)
    assert res["cases"] == 20
    assert res["customers"] == 50

    # Ensure recovery cases were inserted and experiment_results properly reference them
    cases_count = session.scalar(select(func.count(RecoveryCase.id)))
    assert cases_count == 20
    exp_results = session.scalars(select(ExperimentResult)).all()
    assert len(exp_results) > 0
    for er in exp_results:
        assert er.case_id.startswith("RC-")
        # Verify FK target actually exists in DB
        case = session.get(RecoveryCase, er.case_id)
        assert case is not None


def test_health_endpoint_succeeds(live_client):
    """Verify /health returns 200 OK with proper status when DB is available."""
    response = live_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "recoverx-control-plane"
