"""Synthetic Merchant Data Generator for RecoverX.
Generates 1,000+ realistic customers, historical payments, invoices, subscriptions,
checkout attempts, and 500 coherent recovery cases.
"""
from datetime import datetime, timezone, timedelta
import os
import random
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import (
    AgentDecision,
    AuditEvent,
    CheckoutAttempt,
    Communication,
    Customer,
    Escalation,
    Experiment,
    ExperimentResult,
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
    RiskAssessment,
    Subscription,
    User,
)
from app.auth import hash_password
from app.core.config import settings
from app.services.risk_engine import RiskEngine
from app.services.policy_engine import PolicyEngine

NAMES = [
    "Rahul Sharma", "Priya Nair", "Arjun Kapoor", "Meera Shah", "Kavya Iyer",
    "Vikram Rao", "Neha Gupta", "Aarav Mehta", "Ananya Singh", "Rohan Verma",
    "Siddharth Joshi", "Aditi Deshmukh", "Karan Malhotra", "Ritu Patel", "Tarun Saxena",
    "Pooja Bhatia", "Devendra Sen", "Sneha Kulkarni", "Amitabh Das", "Shreya Reddy"
]

FAILURE_REASONS = [
    "insufficient_funds",
    "card_expired",
    "do_not_honor",
    "temporary_technical_error",
    "mandate_decline",
    "payment_timeout",
    "authentication_failed",
]


def generate_synthetic_dataset(
    session: Session,
    customer_count: int = 1000,
    case_count: int = 500,
    seed: int = 20260902,
) -> dict[str, int]:
    rng = random.Random(seed)

    # 1. Clean existing data
    for model in (
        Communication,
        PaymentLink,
        RecoveryAction,
        PromiseToPay,
        Escalation,
        AgentDecision,
        RecoveryCase,
        RiskAssessment,
        RevenueEvent,
        CheckoutAttempt,
        PaymentAttempt,
        Payment,
        Invoice,
        Subscription,
        ExperimentResult,
        Experiment,
        Customer,
        User,
        Policy,
        AuditEvent,
    ):
        session.execute(delete(model))
    session.flush()

    # 2. Create Organization
    org = session.scalar(select(Organization).limit(1))
    if not org:
        org = Organization(
            id=str(uuid4()),
            name="RecoverX Demo Merchant",
            currency="INR",
            timezone="Asia/Kolkata",
        )
        session.add(org)
        session.flush()

    # 3. Create Default Merchant Policy
    policy = Policy(
        id=str(uuid4()),
        organization_id=org.id,
        max_auto_action_amount=25000,
        human_approval_above_amount=25000,
        max_contact_attempts=3,
        escalate_after_days=7,
        min_ai_confidence=0.70,
        preferred_channels="whatsapp,email",
        supported_languages="English,Hinglish",
        allowed_actions="PAYMENT_LINK,PAYMENT_RETRY,REMINDER,PERSONALIZED_OUTREACH,FOLLOW_UP,CHECKOUT_RECOVERY",
        updated_by="RecoverX Setup",
    )
    session.add(policy)
    session.flush()

    # 4. Create Standard RBAC Users (preserving existing bootstrap admin if present)
    users_data = [
        ("ADMIN", "admin@recoverx.local", "RecoverX Admin"),
        ("FINANCE_MANAGER", "finance@recoverx.local", "Finance Manager"),
        ("OPERATOR", "operator@recoverx.local", "Recovery Operator"),
        ("VIEWER", "viewer@recoverx.local", "Recovery Viewer"),
    ]
    bootstrap_raw_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL") or settings.BOOTSTRAP_ADMIN_EMAIL or ""
    bootstrap_email = bootstrap_raw_email.strip().lower().strip("\"'")
    bootstrap_raw_pwd = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or settings.BOOTSTRAP_ADMIN_PASSWORD or ""
    bootstrap_pwd = bootstrap_raw_pwd.strip().strip("\"'")

    for role, email, name in users_data:
        norm_email = email.strip().lower().strip("\"'")
        existing = session.scalar(select(User).where(func.lower(User.email) == norm_email))
        if existing:
            continue

        if role == "ADMIN" and norm_email == bootstrap_email and bootstrap_pwd:
            pwd_hash = hash_password(bootstrap_pwd)
        else:
            pwd_hash = hash_password("recoverx-demo")

        session.add(
            User(
                id=str(uuid4()),
                organization_id=org.id,
                email=norm_email,
                name=name,
                role=role,
                password_hash=pwd_hash,
            )
        )
    session.flush()

    # 5. Create Core Golden Demo Customers: Rahul & Acme Pvt Ltd
    customers: list[Customer] = []

    # Rahul (Golden Demo profile: 18 successful / 19 total payments, 91% reliability)
    rahul = Customer(
        id="cus_rahul_golden_demo",
        organization_id=org.id,
        razorpay_customer_id="cus_rahul_18000",
        name="Rahul Sharma",
        email="rahul.sharma@example.test",
        phone="+919820018000",
        lifetime_value=324000,
        payment_reliability_pct=91.0,
        successful_payments=18,
        failed_payments=1,
        average_payment_amount=18000,
        preferred_channel="whatsapp",
        preferred_language="English",
        historical_recovery_rate=0.88,
        previous_recovery_attempts=1,
        best_historical_recovery_action="PAYMENT_LINK",
        opted_out=False,
    )
    session.add(rahul)
    customers.append(rahul)

    # Acme Pvt Ltd (B2B Golden Demo profile: ₹12,500 failure)
    acme = Customer(
        id="cus_acme_pvt_ltd",
        organization_id=org.id,
        razorpay_customer_id="cus_acme_12500",
        name="Acme Pvt Ltd",
        email="billing@acmepvtltd.test",
        phone="+919810012500",
        lifetime_value=450000,
        payment_reliability_pct=88.0,
        successful_payments=24,
        failed_payments=2,
        average_payment_amount=12500,
        preferred_channel="email",
        preferred_language="English",
        historical_recovery_rate=0.85,
        previous_recovery_attempts=2,
        best_historical_recovery_action="REMINDER",
        opted_out=False,
    )
    session.add(acme)
    customers.append(acme)

    # 6. Generate remaining 1,000+ Customers across realistic distributions
    for index in range(len(customers), customer_count):
        archetype = rng.choice(["enterprise", "high_rel", "mid_rel", "low_rel", "opted_out", "new"])
        name = f"{rng.choice(NAMES)} {index}"

        if archetype == "enterprise":
            reliability = rng.uniform(92.0, 99.0)
            success = rng.randint(25, 60)
            failed = rng.randint(0, 2)
            avg_amt = rng.choice([25000, 45000, 75000, 120000])
            opted = False
        elif archetype == "high_rel":
            reliability = rng.uniform(80.0, 92.0)
            success = rng.randint(10, 30)
            failed = rng.randint(1, 3)
            avg_amt = rng.choice([5000, 12000, 18000, 24000])
            opted = False
        elif archetype == "mid_rel":
            reliability = rng.uniform(65.0, 80.0)
            success = rng.randint(4, 15)
            failed = rng.randint(2, 5)
            avg_amt = rng.choice([2500, 5000, 8500, 15000])
            opted = False
        elif archetype == "low_rel":
            reliability = rng.uniform(45.0, 65.0)
            success = rng.randint(1, 6)
            failed = rng.randint(3, 8)
            avg_amt = rng.choice([1500, 3500, 7000])
            opted = False
        elif archetype == "opted_out":
            reliability = rng.uniform(60.0, 85.0)
            success = rng.randint(3, 10)
            failed = rng.randint(1, 3)
            avg_amt = rng.choice([3000, 6000])
            opted = True
        else:  # new
            reliability = 75.0
            success = rng.randint(1, 3)
            failed = rng.randint(0, 1)
            avg_amt = rng.choice([2000, 4000, 9000])
            opted = False

        c = Customer(
            id=str(uuid4()),
            organization_id=org.id,
            razorpay_customer_id=f"cus_{index + 1:05d}",
            name=name,
            email=f"customer{index + 1}@example.test",
            phone=f"+9199{rng.randint(10000000, 99999999)}",
            lifetime_value=int(avg_amt * success),
            payment_reliability_pct=round(reliability, 1),
            successful_payments=success,
            failed_payments=failed,
            average_payment_amount=avg_amt,
            preferred_channel=rng.choice(["whatsapp", "email"]),
            preferred_language=rng.choice(["English", "Hinglish"]),
            historical_recovery_rate=round(rng.uniform(0.35, 0.92), 2),
            previous_recovery_attempts=rng.randint(0, 4),
            best_historical_recovery_action=rng.choice(["PAYMENT_LINK", "PAYMENT_RETRY", "REMINDER"]),
            opted_out=opted,
        )
        session.add(c)
        customers.append(c)

    session.flush()

    # 7. Create A/B Experiments
    exp = Experiment(
        id=str(uuid4()),
        organization_id=org.id,
        name="Personalized Hinglish vs Generic Reminder",
        description="Testing recovery lift on failed payments ₹5K–₹20K between generic reminder and personalized Hinglish Payment Link",
        segment="Failed payments ₹5K–₹20K",
        status="ACTIVE",
    )
    session.add(exp)
    session.flush()

    # 8. Create Historical Payment Records & Invoices & Subscriptions
    now = datetime.now(timezone.utc)
    for c in customers[:200]:
        # Add 1 successful payment
        p = Payment(
            id=str(uuid4()),
            organization_id=org.id,
            customer_id=c.id,
            provider_payment_id=f"pay_hist_{uuid4().hex[:10]}",
            amount=c.average_payment_amount,
            status="CAPTURED",
            created_at=now - timedelta(days=rng.randint(5, 60)),
        )
        session.add(p)

        # Add 1 subscription
        sub = Subscription(
            id=str(uuid4()),
            organization_id=org.id,
            customer_id=c.id,
            provider_subscription_id=f"sub_{uuid4().hex[:10]}",
            plan_name="RecoverX Premium Monthly",
            amount=c.average_payment_amount,
            status=rng.choice(["ACTIVE", "HALTED", "ACTIVE", "ACTIVE"]),
            next_charge_at=now + timedelta(days=rng.randint(1, 20)),
        )
        session.add(sub)

        # Add 1 invoice
        inv = Invoice(
            id=str(uuid4()),
            organization_id=org.id,
            customer_id=c.id,
            provider_invoice_id=f"inv_{uuid4().hex[:10]}",
            amount=c.average_payment_amount * 2,
            paid_amount=0,
            status=rng.choice(["PAID", "OVERDUE", "PARTIALLY_PAID"]),
            due_at=now - timedelta(days=rng.randint(2, 14)),
        )
        session.add(inv)

    session.flush()

    # 9. Create 500 Coherent Recovery Cases
    # Guarantee Golden Demo Case #1: Rahul, ₹18,000, PAYMENT_FAILURE
    rahul_event = RevenueEvent(
        id=str(uuid4()),
        organization_id=org.id,
        event_type="PAYMENT_FAILURE",
        source="simulated_razorpay",
        source_entity="payment",
        source_id="pay_rahul_18000",
        customer_id=rahul.id,
        amount=18000,
        currency="INR",
        raw_payload={"event": "payment.failed", "amount": 18000, "customer_id": rahul.razorpay_customer_id},
        dedupe_key="golden-demo-rahul-18000",
    )
    rahul_risk = RiskAssessment(
        id=str(uuid4()),
        risk_score=82,
        recovery_probability=0.84,
        expected_recovery_value=15120,
        model_version="deterministic-v2.0",
        factors={"amount": 18000, "reliability_pct": 91.0, "repeat_failures": 0, "overdue_days": 0},
    )
    rahul_case = RecoveryCase(
        id="RC-RAHUL-18K",
        organization_id=org.id,
        revenue_event_id=rahul_event.id,
        customer_id=rahul.id,
        risk_assessment_id=rahul_risk.id,
        status="ACTIONABLE",
        contact_attempts=0,
        amount=18000,
        currency="INR",
        recommended_action="PAYMENT_LINK",
        policy_decision="AUTO_APPROVE",
        ai_confidence=0.91,
        recovered_amount=0,
        action_executed=False,
        failure_reason="ISOLATED_PAYMENT_METHOD_ISSUE",
    )
    rahul_decision = AgentDecision(
        id=str(uuid4()),
        recovery_case_id=rahul_case.id,
        diagnosis="Customer has successfully completed 18 of their previous 19 payments. The current failure appears isolated rather than behavioral. Recovery probability is high.",
        root_cause="ISOLATED_PAYMENT_METHOD_ISSUE",
        recommended_action="PAYMENT_LINK",
        recovery_probability=0.84,
        confidence=0.91,
        reasoning="18 successful historical payments, 1 previous failure, 91% payment reliability -> likely isolated payment method issue. Recommended Payment Link + WhatsApp outreach.",
        model="langgraph-v1",
    )
    session.add_all([rahul_event, rahul_risk, rahul_case, rahul_decision])

    # Guarantee Golden Demo Case #2: Acme Pvt Ltd, ₹12,500
    acme_event = RevenueEvent(
        id=str(uuid4()),
        organization_id=org.id,
        event_type="PAYMENT_FAILURE",
        source="simulated_razorpay",
        source_entity="payment",
        source_id="pay_acme_12500",
        customer_id=acme.id,
        amount=12500,
        currency="INR",
        raw_payload={"event": "payment.failed", "amount": 12500, "customer_id": acme.razorpay_customer_id},
        dedupe_key="golden-demo-acme-12500",
    )
    acme_risk = RiskAssessment(
        id=str(uuid4()),
        risk_score=78,
        recovery_probability=0.82,
        expected_recovery_value=10250,
        model_version="deterministic-v2.0",
        factors={"amount": 12500, "reliability_pct": 88.0, "repeat_failures": 0, "overdue_days": 1},
    )
    acme_case = RecoveryCase(
        id="RC-ACME-12500",
        organization_id=org.id,
        revenue_event_id=acme_event.id,
        customer_id=acme.id,
        risk_assessment_id=acme_risk.id,
        status="ACTIONABLE",
        contact_attempts=0,
        amount=12500,
        currency="INR",
        recommended_action="PAYMENT_RETRY",
        policy_decision="AUTO_APPROVE",
        ai_confidence=0.89,
        recovered_amount=0,
        action_executed=False,
        failure_reason="INSUFFICIENT_FUNDS_OR_LIMIT",
    )
    acme_decision = AgentDecision(
        id=str(uuid4()),
        recovery_case_id=acme_case.id,
        diagnosis="B2B corporate account with recurring billing. Payment degraded due to credit line limit exhaustion.",
        root_cause="INSUFFICIENT_FUNDS_OR_LIMIT",
        recommended_action="PAYMENT_RETRY",
        recovery_probability=0.82,
        confidence=0.89,
        reasoning="24 successful corporate transactions. Retry scheduled for next morning banking hours.",
        model="langgraph-v1",
    )
    session.add_all([acme_event, acme_risk, acme_case, acme_decision])

    # Generate remaining cases (up to case_count)
    amounts = [2400, 4999, 7200, 12000, 18000, 25000, 42500, 68000, 120000]
    event_types = ["PAYMENT_FAILURE", "SUBSCRIPTION_HALTED", "INVOICE_OVERDUE", "CHECKOUT_ABANDONED"]
    pending_experiment_results: list[ExperimentResult] = []

    for index in range(2, case_count):
        customer = customers[index % len(customers)]
        amount = rng.choice(amounts)
        event_type = rng.choice(event_types)
        overdue_days = rng.randint(0, 18)
        repeat_failures = rng.randint(0, 3)

        risk_eval = RiskEngine.evaluate(
            amount=amount,
            customer=customer,
            overdue_days=overdue_days,
            repeat_failures=repeat_failures,
            event_type=event_type,
        )

        event_id = str(uuid4())
        risk_id = str(uuid4())
        case_id = f"RC-{1000 + index}"

        event = RevenueEvent(
            id=event_id,
            organization_id=org.id,
            event_type=event_type,
            source="simulated_razorpay",
            source_entity="payment" if event_type == "PAYMENT_FAILURE" else "invoice" if "INVOICE" in event_type else "subscription",
            source_id=f"pay_{seed}_{index}",
            customer_id=customer.id,
            amount=amount,
            currency="INR",
            raw_payload={"simulated": True, "event_type": event_type, "amount": amount},
            dedupe_key=f"demo-{seed}-{index}",
            occurred_at=now - timedelta(days=overdue_days),
        )

        risk = RiskAssessment(
            id=risk_id,
            risk_score=risk_eval.risk_score,
            recovery_probability=risk_eval.recovery_probability,
            expected_recovery_value=risk_eval.expected_recovery_value,
            model_version=risk_eval.model_version,
            factors=risk_eval.factors,
        )

        # Policy check
        policy_eval = PolicyEngine.evaluate(
            policy=policy,
            case=RecoveryCase(
                id=case_id,
                organization_id=org.id,
                revenue_event_id=event_id,
                customer_id=customer.id,
                risk_assessment_id=risk_id,
                amount=amount,
                contact_attempts=rng.randint(0, 2),
                status="ACTIONABLE",
                ai_confidence=risk_eval.recovery_probability,
            ),
            customer=customer,
            ai_confidence=risk_eval.recovery_probability,
            overdue_days=overdue_days,
        )

        # Determine realistic case status distribution
        if policy_eval.decision == "HUMAN_REVIEW":
            status = "ESCALATED"
        elif policy_eval.decision == "STOP":
            status = "STOPPED"
        else:
            status = "WAITING_FOR_PAYMENT"

        # Simulating realistic historical recovery (approx 60-65% of AUTO_APPROVE cases recovered)
        is_recovered = (status == "WAITING_FOR_PAYMENT") and (rng.random() < risk_eval.recovery_probability * 0.75)
        if is_recovered:
            status = "RECOVERED"
            recovered_amount = amount
            executed = True
        else:
            recovered_amount = 0
            executed = status in ("WAITING_FOR_PAYMENT", "ACTION_EXECUTED")

        recommended_action = "PAYMENT_LINK" if event_type in ("PAYMENT_FAILURE", "CHECKOUT_ABANDONED") else "REMINDER" if "INVOICE" in event_type else "PAYMENT_RETRY"

        case = RecoveryCase(
            id=case_id,
            organization_id=org.id,
            revenue_event_id=event_id,
            customer_id=customer.id,
            risk_assessment_id=risk_id,
            status=status,
            contact_attempts=1 if executed else 0,
            amount=amount,
            currency="INR",
            recommended_action=recommended_action,
            policy_decision=policy_eval.decision,
            ai_confidence=risk_eval.recovery_probability,
            recovered_amount=recovered_amount,
            action_executed=executed,
            failure_reason=rng.choice(FAILURE_REASONS),
            created_at=now - timedelta(days=overdue_days),
        )

        decision = AgentDecision(
            id=str(uuid4()),
            recovery_case_id=case.id,
            diagnosis=f"{event_type.replace('_', ' ').title()} diagnosed with {int(customer.payment_reliability_pct)}% reliability track record.",
            root_cause="ISOLATED_PAYMENT_METHOD_ISSUE" if customer.payment_reliability_pct > 80 else "INSUFFICIENT_FUNDS_OR_LIMIT",
            recommended_action=recommended_action,
            recovery_probability=risk_eval.recovery_probability,
            confidence=risk_eval.recovery_probability,
            reasoning=f"Selected {recommended_action} via {customer.preferred_channel} based on customer preference.",
            model="langgraph-v1",
        )

        session.add_all([event, risk, case, decision])

        # If executed, create PaymentLink & Communication
        if executed:
            link = PaymentLink(
                id=f"pl_{uuid4().hex[:12]}",
                case_id=case.id,
                provider_link_id=f"plink_{uuid4().hex[:10]}",
                amount=amount,
                status="PAID" if is_recovered else "OPEN",
                short_url=f"https://rzp.io/i/pl_{case.id}",
                created_at=case.created_at,
            )
            comm = Communication(
                id=str(uuid4()),
                case_id=case.id,
                customer_id=customer.id,
                channel=customer.preferred_channel.upper(),
                direction="OUTBOUND",
                content=f"Payment link for {amount} INR",
                status="DELIVERED" if is_recovered else "SENT",
                created_at=case.created_at,
            )
            session.add_all([link, comm])

        # Record A/B test variant assignment
        variant = rng.choice(["Variant A", "Variant B"])
        pending_experiment_results.append(
            ExperimentResult(
                id=str(uuid4()),
                experiment_id=exp.id,
                case_id=case.id,
                variant=variant,
                outcome=status if status in ("RECOVERED", "STOPPED", "ESCALATED") else None,
                revenue=recovered_amount,
            )
        )

    # Flush all RecoveryCases and related core records before inserting dependent ExperimentResults
    session.flush()

    # Persist ExperimentResults now that RecoveryCases are guaranteed to be present in DB
    for exp_res in pending_experiment_results:
        session.add(exp_res)
    session.flush()

    # Log master seed audit
    session.add(
        AuditEvent(
            id=str(uuid4()),
            organization_id=org.id,
            actor="system_seeder",
            event_name="demo.dataset.seeded",
            payload={"customer_count": customer_count, "case_count": case_count, "seed": seed},
        )
    )
    session.commit()

    return {
        "customers": customer_count,
        "cases": case_count,
        "seed": seed,
    }
