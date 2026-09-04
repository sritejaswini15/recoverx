"""Durable Recovery Workflow definition.
Manages multi-day payment recovery, waiting periods, payment verification, follow-ups, and escalation.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session
from app.db import RecoveryCase, PaymentLink, AuditEvent
from app.services.tool_gateway import default_gateway


@dataclass
class WorkflowState:
    case_id: str
    stage: str  # INITIAL_ATTEMPT, WAITING_PAYMENT_1, FOLLOWUP_1, WAITING_PAYMENT_2, COMPLETED, ESCALATED
    payment_verified: bool = False
    next_check_at: datetime | None = None
    attempts: int = 1


class RecoveryWorkflow:
    def __init__(self, case_id: str, session: Session) -> None:
        self.case_id = case_id
        self.session = session

    def execute_step(self, simulated_fast_forward_days: int = 0) -> dict[str, Any]:
        case = self.session.get(RecoveryCase, self.case_id)
        if not case:
            return {"error": "Case not found", "status": "UNKNOWN"}

        if case.status in ("RECOVERED", "STOPPED", "ESCALATED"):
            return {"status": case.status, "message": "Workflow already completed"}

        # 1. Check if customer already paid
        link = self.session.query(PaymentLink).filter_by(case_id=self.case_id).first()
        if link and link.status == "PAID":
            case.status = "RECOVERED"
            case.recovered_amount = case.amount
            self._log_audit(case, "workflow.completed", {"recovered": True, "amount": case.amount})
            self.session.flush()
            return {"status": "RECOVERED", "recovered_amount": case.amount}

        # 2. Progress state based on contact attempts
        if case.contact_attempts == 1:
            # First touch completed -> schedule follow-up
            if simulated_fast_forward_days < 2:
                next_check_at = datetime.now(timezone.utc) + timedelta(days=2 - simulated_fast_forward_days)
                return {
                    "status": "WAITING_FOR_PAYMENT",
                    "attempts": case.contact_attempts,
                    "next_check_at": next_check_at.isoformat(),
                }

            action = default_gateway.execute_recovery_action(
                session=self.session,
                case=case,
                action_type="REMINDER",
                actor="temporal_workflow",
            )
            self._log_audit(case, "workflow.followup_sent", {"action_id": action.id, "attempt": case.contact_attempts})
            return {"status": "FOLLOWUP_DISPATCHED", "attempts": case.contact_attempts}

        elif case.contact_attempts >= 2:
            # Multiple touches without payment -> escalate
            escalation = default_gateway.create_escalation(
                session=self.session,
                case_id=case.id,
                reason="MAX_ATTEMPTS",
                notes="Automated recovery workflow completed 2 attempts without payment.",
                actor="temporal_workflow",
            )
            self._log_audit(case, "workflow.escalated", {"escalation_id": escalation.id})
            return {"status": "ESCALATED", "escalation_id": escalation.id}

        return {"status": case.status, "contact_attempts": case.contact_attempts}

    def _log_audit(self, case: RecoveryCase, event_name: str, payload: dict[str, Any]) -> None:
        self.session.add(
            AuditEvent(
                id=str(uuid4()),
                organization_id=case.organization_id,
                case_id=case.id,
                actor="workflow_engine",
                event_name=event_name,
                payload=payload,
            )
        )
