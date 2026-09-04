"""500-Case Batch Evaluation Service for RecoverX.
Evaluates synthetic cases through the full pipeline measuring accuracy, policy compliance, and financial outcomes.
"""
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.recovery_graph import recovery_graph
from app.db import AuditEvent, Customer, Policy, RecoveryAction, RecoveryCase
from app.schemas.agent import RecoveryDecision
from app.services.policy_engine import PolicyEngine
from app.services.risk_engine import RiskEngine


class EvaluationService:
    @staticmethod
    def run_evaluation(session: Session, organization_id: str | None = None) -> dict[str, Any]:
        query = select(RecoveryCase)
        if organization_id:
            query = query.where(RecoveryCase.organization_id == organization_id)
        cases = session.scalars(query).all()
        total_cases = len(cases)
        if total_cases == 0:
            return {"error": "No cases available for evaluation. Please seed dataset first."}

        policy_by_org = {
            policy.organization_id: policy
            for policy in session.scalars(select(Policy)).all()
        }
        invalid_ai_decisions = 0
        policy_violations = 0
        false_escalations = 0
        evaluated_probabilities: list[float] = []
        recovered_durations: list[float] = []

        for case in cases:
            customer = case.customer
            event = case.revenue_event
            risk = RiskEngine.evaluate(
                amount=case.amount,
                customer=customer,
                event_type=event.event_type if event else "PAYMENT_FAILURE",
            )
            graph_valid = True
            try:
                graph_result = recovery_graph.invoke({
                    "organization_id": case.organization_id,
                    "event_type": event.event_type if event else "PAYMENT_FAILURE",
                    "amount": case.amount,
                    "currency": case.currency,
                    "customer_id": case.customer_id,
                    "customer_name": customer.name if customer else "Customer",
                    "customer_reliability": customer.payment_reliability_pct if customer else 70.0,
                    "successful_payments": customer.successful_payments if customer else 0,
                    "failed_payments": customer.failed_payments if customer else 0,
                    "preferred_channel": customer.preferred_channel if customer else "whatsapp",
                    "preferred_language": customer.preferred_language if customer else "English",
                })
                RecoveryDecision(
                    diagnosis=graph_result.get("diagnosis", ""),
                    root_cause=graph_result.get("root_cause", ""),
                    recovery_probability=graph_result.get("recovery_probability", risk.recovery_probability),
                    recommended_action=graph_result.get("recommended_action", "NO_ACTION"),
                    reasoning=graph_result.get("ai_reasoning", ""),
                    confidence=graph_result.get("ai_confidence", 0.0),
                    suggested_language=graph_result.get("suggested_language", "English"),
                )
                evaluated_probabilities.append(float(graph_result.get("recovery_probability", risk.recovery_probability)))
                policy = policy_by_org.get(case.organization_id)
                if policy:
                    overdue_days = (
                        max(
                            0,
                            (
                                datetime.now(timezone.utc)
                                - (
                                    event.occurred_at.replace(tzinfo=timezone.utc)
                                    if event.occurred_at.tzinfo is None
                                    else event.occurred_at
                                )
                            ).days,
                        )
                        if event and event.occurred_at
                        else 0
                    )
                    policy_result = PolicyEngine.evaluate(
                        policy,
                        case,
                        customer,
                        ai_confidence=float(graph_result.get("ai_confidence", 0.0)),
                        overdue_days=overdue_days,
                    )
                    if case.action_executed and case.status not in ("RECOVERED", "STOPPED") and policy_result.decision != "AUTO_APPROVE":
                        policy_violations += 1
                    if case.status == "ESCALATED" and policy_result.decision == "AUTO_APPROVE":
                        false_escalations += 1
            except Exception:
                graph_valid = False
                invalid_ai_decisions += 1

            if graph_valid and not session.scalar(
                select(AuditEvent).where(
                    AuditEvent.case_id == case.id,
                    AuditEvent.event_name == "evaluation.case_processed",
                    AuditEvent.correlation_id == f"evaluation:{case.id}",
                )
            ):
                session.add(AuditEvent(
                    id=f"eval_{case.id}",
                    organization_id=case.organization_id,
                    case_id=case.id,
                    actor="batch_evaluator",
                    event_name="evaluation.case_processed",
                    payload={"risk_score": risk.risk_score, "decision_valid": True},
                    correlation_id=f"evaluation:{case.id}",
                ))
            if case.status == "RECOVERED":
                recovered_durations.append(max(0.0, (case.updated_at - case.created_at).total_seconds() / 3600))

        session.flush()

        at_risk = sum(c.amount for c in cases)
        recovered = sum(c.recovered_amount for c in cases)
        successful = sum(1 for c in cases if c.status == "RECOVERED")
        escalated = sum(1 for c in cases if c.status == "ESCALATED")
        stopped = sum(1 for c in cases if c.status == "STOPPED")

        targeted = sum(
            c.risk_assessment.expected_recovery_value
            for c in cases
            if c.policy_decision != "STOP" and c.risk_assessment
        )
        avg_prob = sum(evaluated_probabilities) / len(evaluated_probabilities) if evaluated_probabilities else 0.0
        avg_confidence = (
            sum(c.ai_confidence for c in cases) / total_cases if total_cases else 0.0
        )

        recovery_rate = round(recovered / at_risk, 4) if at_risk else 0.0
        action_failures = session.scalar(
            select(func.count(RecoveryAction.id)).join(RecoveryCase).where(RecoveryAction.status == "FAILED")
        ) or 0
        average_recovery_time = sum(recovered_durations) / len(recovered_durations) if recovered_durations else 0.0

        return {
            "cases_processed": total_cases,
            "revenue_at_risk": at_risk,
            "revenue_targeted": targeted,
            "revenue_recovered": recovered,
            "recovery_rate": recovery_rate,
            "average_recovery_probability": round(avg_prob, 4),
            "average_ai_confidence": round(avg_confidence, 4),
            "successful_recoveries": successful,
            "escalations": escalated,
            "false_escalations": false_escalations,
            "policy_violations": policy_violations,
            "invalid_ai_decisions": invalid_ai_decisions,
            "action_failures": action_failures,
            "average_recovery_time_hours": round(average_recovery_time, 2),
            "evaluation_status": "PASSED" if policy_violations == 0 and invalid_ai_decisions == 0 else "FAILED",
        }
