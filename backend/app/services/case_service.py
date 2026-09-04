"""Recovery Case Service for RecoverX.
Coordinates event ingestion, normalization, risk assessment, LangGraph decisioning,
policy evaluation, and tool gateway execution.
"""
from datetime import datetime, timezone
from typing import Any, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.recovery_graph import recovery_graph
from app.db import (
    AgentDecision,
    AuditEvent,
    Customer,
    Organization,
    PaymentLink,
    Payment,
    PaymentAttempt,
    Policy,
    RecoveryAction,
    RecoveryCase,
    RevenueEvent,
    RiskAssessment,
)
from app.services.event_normalizer import normalize_event
from app.services.policy_engine import PolicyEngine
from app.services.risk_engine import RiskEngine
from app.services.tool_gateway import default_gateway
from app.workflows.runner import workflow_runner


class CaseService:
    @classmethod
    def get_or_create_policy(cls, session: Session, organization_id: str) -> Policy:
        policy = session.scalar(select(Policy).where(Policy.organization_id == organization_id))
        if not policy:
            policy = Policy(
                id=str(uuid4()),
                organization_id=organization_id,
                max_auto_action_amount=25000,
                human_approval_above_amount=25000,
                max_contact_attempts=3,
                escalate_after_days=7,
                min_ai_confidence=0.70,
                preferred_channels="whatsapp,email",
                supported_languages="English,Hinglish",
                allowed_actions="PAYMENT_LINK,PAYMENT_RETRY,REMINDER,PERSONALIZED_OUTREACH,FOLLOW_UP,CHECKOUT_RECOVERY",
            )
            session.add(policy)
            session.flush()
        return policy

    @classmethod
    def process_event(
        cls,
        session: Session,
        org: Organization,
        customer: Customer,
        raw_body: dict[str, Any],
        dedupe_key: str,
        actor: str = "webhook",
    ) -> Tuple[RevenueEvent, RecoveryCase | None, bool]:
        """Ingests, normalizes, and processes a revenue event through the complete RecoverX pipeline."""
        # 1. Deduplication Check
        existing_event = session.scalar(select(RevenueEvent).where(RevenueEvent.dedupe_key == dedupe_key))
        if existing_event:
            # Replay protection: match existing case if present
            case = session.scalar(select(RecoveryCase).where(RecoveryCase.revenue_event_id == existing_event.id))
            return existing_event, case, True

        # 2. Canonical Normalization
        canonical = normalize_event(raw_body)

        # 3. Raw Event Persistence
        event = RevenueEvent(
            id=str(uuid4()),
            organization_id=org.id,
            event_type=canonical.event_type,
            source=canonical.source,
            source_entity=canonical.source_entity,
            source_id=canonical.source_id,
            customer_id=customer.id,
            amount=canonical.amount,
            currency=canonical.currency,
            raw_payload=raw_body,
            dedupe_key=dedupe_key,
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(event)
        session.flush()

        # Mirror provider payment state before risk/action processing so retries
        # always operate on a persisted financial record.
        if canonical.source_entity == "payment":
            payment = session.scalar(select(Payment).where(Payment.provider_payment_id == canonical.source_id))
            is_new_payment = payment is None
            if payment is None:
                payment = Payment(
                    id=str(uuid4()),
                    organization_id=org.id,
                    customer_id=customer.id,
                    provider_payment_id=canonical.source_id,
                    amount=canonical.amount,
                    currency=canonical.currency,
                    status="CREATED",
                )
                session.add(payment)
                session.flush()

            if canonical.event_type in ("PAYMENT_CAPTURED", "PAYMENT_AUTHORIZED"):
                payment.status = "CAPTURED"
                attempt_status = "SUCCESS"
                payment.failure_reason = None
            elif canonical.event_type == "PAYMENT_FAILURE":
                payment.status = "FAILED"
                payment.failure_reason = canonical.metadata.get("error_description") or "payment_failed"
                attempt_status = "FAILED"
            else:
                attempt_status = None

            if attempt_status:
                session.add(
                    PaymentAttempt(
                        id=str(uuid4()),
                        payment_id=payment.id,
                        provider_attempt_id=f"webhook_{event.id}",
                        status=attempt_status,
                        failure_reason=payment.failure_reason,
                    )
                )
            if is_new_payment:
                session.flush()

        # 4. Handle Payment Success / Resolution Events
        if canonical.event_type in (
            "PAYMENT_CAPTURED",
            "PAYMENT_AUTHORIZED",
            "PAYMENT_LINK_PAID",
            "INVOICE_PAID",
            "SUBSCRIPTION_CHARGED",
        ):
            # Check for payment link matching source_id
            link = session.scalar(
                select(PaymentLink).where(
                    (PaymentLink.provider_link_id == canonical.source_id)
                    | (PaymentLink.id == canonical.source_id)
                )
            )
            matched_case = None
            if link:
                link.status = "PAID"
                matched_case = session.get(RecoveryCase, link.case_id)
            
            if not matched_case:
                # A payment event may resolve the case tied to the same provider payment.
                matched_case = session.scalar(
                    select(RecoveryCase)
                    .join(RevenueEvent, RevenueEvent.id == RecoveryCase.revenue_event_id)
                    .where(
                        RecoveryCase.organization_id == org.id,
                        RevenueEvent.source_id == canonical.source_id,
                        RecoveryCase.status.in_(("NEW", "ANALYZING", "ACTIONABLE", "ACTION_PENDING", "ACTION_EXECUTED", "WAITING_FOR_PAYMENT", "ESCALATED", "PROMISE_TO_PAY")),
                    )
                )

            if not matched_case:
                # Simulated and real Payment Link callbacks may carry RecoverX's
                # case reference in provider notes. Keep the lookup tenant-scoped.
                case_reference = (canonical.metadata.get("notes") or {}).get("case_id")
                if case_reference:
                    matched_case = session.scalar(
                        select(RecoveryCase).where(
                            RecoveryCase.id == case_reference,
                            RecoveryCase.organization_id == org.id,
                            RecoveryCase.customer_id == customer.id,
                            RecoveryCase.status.in_(
                                ("NEW", "ANALYZING", "ACTIONABLE", "ACTION_PENDING", "ACTION_EXECUTED", "WAITING_FOR_PAYMENT", "ESCALATED", "PROMISE_TO_PAY")
                            ),
                        )
                    )

            if matched_case:
                matched_case.status = "RECOVERED"
                matched_case.recovered_amount = canonical.amount or matched_case.amount
                session.add(
                    AuditEvent(
                        id=str(uuid4()),
                        organization_id=org.id,
                        case_id=matched_case.id,
                        actor=actor,
                        event_name="payment.recovered",
                        payload={"amount": matched_case.recovered_amount, "event_type": canonical.event_type},
                        correlation_id=dedupe_key,
                    )
                )
                session.add(
                    AuditEvent(
                        id=str(uuid4()),
                        organization_id=org.id,
                        case_id=matched_case.id,
                        actor=actor,
                        event_name="workflow.closed",
                        payload={"resolution": "SUCCESS", "recovered_amount": matched_case.recovered_amount},
                        correlation_id=dedupe_key,
                    )
                )

            session.flush()
            return event, matched_case, False

        # 5. Handle Revenue Leak Events (Payment Failure, Invoices, Subscriptions, Abandonment)
        policy = cls.get_or_create_policy(session, org.id)

        # Risk Engine Evaluation
        risk_res = RiskEngine.evaluate(
            amount=canonical.amount,
            customer=customer,
            overdue_days=raw_body.get("overdue_days", 0),
            repeat_failures=raw_body.get("repeat_failures", 0),
            event_type=canonical.event_type,
        )

        risk_assessment = RiskAssessment(
            id=str(uuid4()),
            risk_score=risk_res.risk_score,
            recovery_probability=risk_res.recovery_probability,
            expected_recovery_value=risk_res.expected_recovery_value,
            model_version=risk_res.model_version,
            factors=risk_res.factors,
        )
        session.add(risk_assessment)
        session.flush()

        # Run LangGraph AI Recovery Agent
        graph_input = {
            "organization_id": org.id,
            "event_type": canonical.event_type,
            "amount": canonical.amount,
            "currency": canonical.currency,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_reliability": customer.payment_reliability_pct,
            "successful_payments": customer.successful_payments,
            "failed_payments": customer.failed_payments,
            "preferred_channel": customer.preferred_channel,
            "preferred_language": customer.preferred_language,
            "overdue_days": raw_body.get("overdue_days", 0),
            "repeat_failures": raw_body.get("repeat_failures", 0),
            # Pass DB policy values so policy_gate uses merchant-configured limits
            "policy_max_amount": policy.max_auto_action_amount,
            "policy_min_confidence": policy.min_ai_confidence,
            "policy_max_attempts": policy.max_contact_attempts,
        }
        graph_result = recovery_graph.invoke(graph_input)

        recommended_action = graph_result.get("recommended_action", "PAYMENT_LINK")
        ai_confidence = graph_result.get("ai_confidence", risk_res.recovery_probability)
        diagnosis = graph_result.get("diagnosis", "Transaction failed")
        root_cause = graph_result.get("root_cause", "PAYMENT_METHOD_DECLINE")
        reasoning = graph_result.get("ai_reasoning", "Recommended recovery intervention")

        # Create Recovery Case
        case_id = f"RC-{uuid4().hex[:8].upper()}"
        initial_status = "ACTIONABLE"

        case = RecoveryCase(
            id=case_id,
            organization_id=org.id,
            revenue_event_id=event.id,
            customer_id=customer.id,
            risk_assessment_id=risk_assessment.id,
            status=initial_status,
            amount=canonical.amount,
            currency=canonical.currency,
            recommended_action=recommended_action,
            policy_decision="PENDING",
            ai_confidence=ai_confidence,
            failure_reason=root_cause,
        )
        session.add(case)
        session.flush()

        # Evaluate Policy Engine with case
        policy_eval = PolicyEngine.evaluate(
            policy=policy,
            case=case,
            customer=customer,
            ai_confidence=ai_confidence,
            overdue_days=raw_body.get("overdue_days", 0),
        )
        case.policy_decision = policy_eval.decision

        # Store Agent Decision
        decision_record = AgentDecision(
            id=str(uuid4()),
            recovery_case_id=case.id,
            diagnosis=diagnosis,
            root_cause=root_cause,
            recommended_action=recommended_action,
            recovery_probability=risk_res.recovery_probability,
            confidence=ai_confidence,
            reasoning=reasoning,
            model="langgraph-v1",
        )
        session.add(decision_record)

        # Audit Trails for Case Creation & Risk Assessment
        session.add(
            AuditEvent(
                id=str(uuid4()),
                organization_id=org.id,
                case_id=case.id,
                actor=actor,
                event_name="revenue_event.received",
                payload={"event_type": canonical.event_type, "amount": canonical.amount},
                correlation_id=dedupe_key,
            )
        )
        session.add(
            AuditEvent(
                id=str(uuid4()),
                organization_id=org.id,
                case_id=case.id,
                actor=actor,
                event_name="risk.assessed",
                payload={
                    "risk_score": risk_res.risk_score,
                    "expected_recovery_value": risk_res.expected_recovery_value,
                    "recovery_probability": risk_res.recovery_probability,
                },
                correlation_id=dedupe_key,
            )
        )
        session.add(
            AuditEvent(
                id=str(uuid4()),
                organization_id=org.id,
                case_id=case.id,
                actor=actor,
                event_name="agent.decision.created",
                payload={
                    "root_cause": root_cause,
                    "action": recommended_action,
                    "confidence": ai_confidence,
                },
                correlation_id=dedupe_key,
            )
        )
        session.add(
            AuditEvent(
                id=str(uuid4()),
                organization_id=org.id,
                case_id=case.id,
                actor=actor,
                event_name="policy.evaluated",
                payload={
                    "decision": policy_eval.decision,
                    "reasons": policy_eval.reasons,
                    "violations": policy_eval.rule_violations,
                },
                correlation_id=dedupe_key,
            )
        )

        # Execute Tool Gateway if AUTO_APPROVE
        if policy_eval.decision == "AUTO_APPROVE":
            default_gateway.execute_recovery_action(
                session=session,
                case=case,
                action_type=recommended_action,
                actor=actor,
                trace_id=dedupe_key,
            )
            workflow_runner.trigger_recovery_workflow(session, case.id)
        elif policy_eval.decision == "HUMAN_REVIEW":
            case.status = "ESCALATED"
            default_gateway.create_escalation(
                session=session,
                case_id=case.id,
                reason=",".join(policy_eval.rule_violations) or "POLICY_REVIEW_REQUIRED",
                actor=actor,
            )
        elif policy_eval.decision == "STOP":
            case.status = "STOPPED"
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    organization_id=org.id,
                    case_id=case.id,
                    actor=actor,
                    event_name="workflow.stopped",
                    payload={"reasons": policy_eval.reasons},
                    correlation_id=dedupe_key,
                )
            )

        session.flush()
        return event, case, False
