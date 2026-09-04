"""Promise-to-Pay workflow monitor.
Checks payment verification on promised date and executes fulfillment or escalation.
"""
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session
from app.db import AuditEvent, PaymentLink, PromiseToPay, RecoveryCase
from app.services.tool_gateway import default_gateway


class PromiseToPayWorkflow:
    def __init__(self, promise_id: str, session: Session) -> None:
        self.promise_id = promise_id
        self.session = session

    def evaluate_commitment(self) -> dict[str, Any]:
        promise = self.session.get(PromiseToPay, self.promise_id)
        if not promise:
            return {"error": "Promise not found"}

        case = self.session.get(RecoveryCase, promise.case_id)
        if not case:
            return {"error": "Case not found"}

        link = self.session.query(PaymentLink).filter_by(case_id=case.id).first()

        # Check if paid
        if (link and link.status == "PAID") or promise.fulfilled:
            promise.fulfilled = True
            promise.status = "FULFILLED"
            case.status = "RECOVERED"
            case.recovered_amount = promise.amount
            self.session.add(
                AuditEvent(
                    id=str(uuid4()),
                    organization_id=case.organization_id,
                    case_id=case.id,
                    actor="promise_workflow",
                    event_name="promise.fulfilled",
                    payload={"promise_id": promise.id, "amount": promise.amount},
                )
            )
            self.session.flush()
            return {"status": "FULFILLED", "case_status": "RECOVERED"}

        now = datetime.now(timezone.utc)
        if promise.promised_date < now:
            # Overdue promise -> escalate
            promise.status = "BROKEN"
            escalation = default_gateway.create_escalation(
                session=self.session,
                case_id=case.id,
                reason="MISSED_PROMISE_TO_PAY",
                notes=f"Customer missed promised payment date of {promise.promised_date.date()}",
                actor="promise_workflow",
            )
            self.session.add(
                AuditEvent(
                    id=str(uuid4()),
                    organization_id=case.organization_id,
                    case_id=case.id,
                    actor="promise_workflow",
                    event_name="promise.broken",
                    payload={"promise_id": promise.id},
                )
            )
            self.session.flush()
            return {"status": "BROKEN", "case_status": "ESCALATED"}

        return {"status": promise.status, "promised_date": promise.promised_date.isoformat()}
