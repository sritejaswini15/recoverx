"""Controlled Tool Gateway for RecoverX.
The sole authorized boundary for executing external financial, payment, and communication actions.
Enforces idempotency, policy gates, audit logging, and provider abstraction.
"""
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import (
    AuditEvent,
    Communication,
    Customer,
    Escalation,
    PaymentLink,
    Policy,
    PromiseToPay,
    RecoveryAction,
    RecoveryCase,
)
from app.services.policy_engine import PolicyEngine
from app.providers import (
    PaymentProvider,
    RazorpayProvider,
    SimulatedEmailProvider,
    SimulatedRazorpayProvider,
    SimulatedWhatsAppProvider,
)


class ToolGateway:
    def __init__(
        self,
        payment_provider: PaymentProvider | None = None,
        whatsapp_provider: SimulatedWhatsAppProvider | None = None,
        email_provider: SimulatedEmailProvider | None = None,
    ) -> None:
        self.payment_provider = payment_provider or (
            RazorpayProvider()
            if settings.PAYMENT_PROVIDER == "razorpay"
            else SimulatedRazorpayProvider()
        )
        self.whatsapp_provider = whatsapp_provider or SimulatedWhatsAppProvider()
        self.email_provider = email_provider or SimulatedEmailProvider()

    def execute_recovery_action(
        self,
        session: Session,
        case: RecoveryCase,
        action_type: str,
        actor: str = "system",
        trace_id: str | None = None,
        organization_id: str | None = None,
        human_approved_by: str | None = None,
    ) -> RecoveryAction:
        """Executes a policy-approved recovery action with full idempotency and auditing."""
        if organization_id and case.organization_id != organization_id:
            raise ValueError("Recovery case does not belong to the authenticated organization")

        customer = session.get(Customer, case.customer_id)
        policy = session.scalar(select(Policy).where(Policy.organization_id == case.organization_id))
        if not policy:
            raise ValueError("Recovery policy not found")
        policy_result = PolicyEngine.evaluate(policy, case, customer)
        action_type = action_type.upper()
        allowed_actions = {value.strip().upper() for value in policy.allowed_actions.split(",") if value.strip()}
        if action_type.upper() not in allowed_actions and not (
            action_type in {"PERSONALIZED_OUTREACH", "FOLLOW_UP", "CHECKOUT_RECOVERY"} and "PAYMENT_LINK" in allowed_actions
        ):
            policy_result = None
            raise ValueError(f"Action {action_type} is prohibited by merchant policy")
        if policy_result.decision != "AUTO_APPROVE":
            if not human_approved_by:
                raise ValueError(f"Action requires policy decision {policy_result.decision}")

        trace = trace_id or str(uuid4())
        if human_approved_by and policy_result.decision == "STOP":
            raise ValueError("Action is stopped by policy and cannot be approved")
        idempotency_key = f"action:{case.id}:{action_type}:{case.contact_attempts}"

        # 1. Idempotency Check
        existing_action = session.scalar(
            select(RecoveryAction).where(RecoveryAction.idempotency_key == idempotency_key)
        )
        if existing_action and existing_action.status == "EXECUTED":
            return existing_action

        action = existing_action or RecoveryAction(
            id=str(uuid4()),
            recovery_case_id=case.id,
            action_type=action_type,
            status="PENDING",
            idempotency_key=idempotency_key,
            trace_id=trace,
            payload={"amount": case.amount, "action_type": action_type},
        )
        if not existing_action:
            session.add(action)
        session.flush()

        preferred_channel = (customer.preferred_channel if customer else "whatsapp").lower()
        preferred_language = (customer.preferred_language if customer else "English").capitalize()

        try:
            # 2. Execute Payment / Link operations
            link_result = None
            # Every customer-facing recovery message contains a provider-created
            # link.  Never synthesize a payment URL in message content: the
            # provider/database remains the source of truth for payment actions.
            if action_type in (
                "PAYMENT_LINK", "PERSONALIZED_OUTREACH", "CHECKOUT_RECOVERY",
                "REMINDER", "FOLLOW_UP",
            ):
                link_result = self.payment_provider.create_payment_link(
                    session=session,
                    case_id=case.id,
                    amount=case.amount,
                    description=f"Payment for {case.id}",
                )
                action.payload = {
                    **action.payload,
                    "payment_url": link_result.public_url,
                    "provider_link_id": link_result.provider_link_id,
                }
                self._add_audit(
                    session=session,
                    org_id=case.organization_id,
                    case_id=case.id,
                    actor=actor,
                    event_name="payment_link.created",
                    payload={"link_id": link_result.provider_link_id, "amount": case.amount},
                    correlation_id=trace,
                )

            elif action_type == "PAYMENT_RETRY":
                # Find associated payment
                payment_result = self.payment_provider.retry_payment(
                    session=session,
                    payment_id=case.revenue_event.source_id,
                )
                self._add_audit(
                    session=session,
                    org_id=case.organization_id,
                    case_id=case.id,
                    actor=actor,
                    event_name="payment.retried",
                    payload={"payment_id": payment_result.provider_payment_id, "status": payment_result.status},
                    correlation_id=trace,
                )

            # 3. Draft & Dispatch Localized Communication
            content = self._format_message(
                customer_name=customer.name if customer else "Customer",
                amount=case.amount,
                language=preferred_language,
                link_url=link_result.short_url if link_result else "",
                action_type=action_type,
            )

            if preferred_channel == "whatsapp":
                recipient = customer.phone if customer else "+919900000000"
                msg_res = self.whatsapp_provider.send_message(
                    session=session,
                    case_id=case.id,
                    customer_id=case.customer_id,
                    recipient=recipient,
                    content=content,
                )
            else:
                recipient = customer.email if customer else "customer@example.test"
                msg_res = self.email_provider.send_message(
                    session=session,
                    case_id=case.id,
                    customer_id=case.customer_id,
                    recipient=recipient,
                    content=content,
                )

            self._add_audit(
                session=session,
                org_id=case.organization_id,
                case_id=case.id,
                actor=actor,
                event_name="message.sent",
                payload={"channel": preferred_channel, "message_id": msg_res.message_id, "recipient": recipient},
                correlation_id=trace,
            )

            action.status = "EXECUTED"
            case.action_executed = True
            case.status = "WAITING_FOR_PAYMENT"
            case.contact_attempts += 1

            self._add_audit(
                session=session,
                org_id=case.organization_id,
                case_id=case.id,
                actor=actor,
                event_name="action.executed",
                payload={"action_id": action.id, "action_type": action_type, "status": "EXECUTED"},
                correlation_id=trace,
            )

        except Exception as e:
            action.status = "FAILED"
            action.payload = {**action.payload, "error": str(e)}
            self._add_audit(
                session=session,
                org_id=case.organization_id,
                case_id=case.id,
                actor=actor,
                event_name="action.failed",
                payload={"action_id": action.id, "error": str(e)},
                correlation_id=trace,
            )
            raise e

        session.flush()
        return action

    def cancel_payment_link(self, session: Session, case_id: str, actor: str = "system") -> bool:
        case = session.get(RecoveryCase, case_id)
        cancelled = self.payment_provider.cancel_payment_link(session, case_id)
        if cancelled and case:
            self._add_audit(
                session=session,
                org_id=case.organization_id,
                case_id=case.id,
                actor=actor,
                event_name="payment_link.cancelled",
                payload={"case_id": case_id},
            )
        return cancelled

    def create_escalation(
        self,
        session: Session,
        case_id: str,
        reason: str,
        assigned_to_user_id: str | None = None,
        notes: str | None = None,
        actor: str = "system",
    ) -> Escalation:
        case = session.get(RecoveryCase, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")

        escalation = session.scalar(select(Escalation).where(Escalation.case_id == case_id))
        if not escalation:
            escalation = Escalation(
                id=str(uuid4()),
                case_id=case_id,
                reason=reason,
                assigned_to_user_id=assigned_to_user_id,
                resolution_notes=notes,
            )
            session.add(escalation)
        else:
            escalation.reason = reason
            escalation.resolution_notes = notes

        case.status = "ESCALATED"
        self._add_audit(
            session=session,
            org_id=case.organization_id,
            case_id=case.id,
            actor=actor,
            event_name="escalation.created",
            payload={"reason": reason, "assigned_to": assigned_to_user_id},
        )
        session.flush()
        return escalation

    def record_promise_to_pay(
        self,
        session: Session,
        case_id: str,
        amount: int,
        promised_date: datetime,
        notes: str | None = None,
        actor: str = "system",
    ) -> PromiseToPay:
        case = session.get(RecoveryCase, case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")

        promise = PromiseToPay(
            id=str(uuid4()),
            case_id=case_id,
            customer_id=case.customer_id,
            amount=amount,
            promised_date=promised_date,
            notes=notes,
            status="PENDING",
        )
        session.add(promise)
        case.status = "PROMISE_TO_PAY"
        self._add_audit(
            session=session,
            org_id=case.organization_id,
            case_id=case.id,
            actor=actor,
            event_name="promise.created",
            payload={"amount": amount, "promised_date": promised_date.isoformat()},
        )
        session.flush()
        return promise

    def _format_message(
        self,
        customer_name: str,
        amount: int,
        language: str,
        link_url: str,
        action_type: str,
    ) -> str:
        first_name = customer_name.split()[0] if customer_name else "there"
        formatted_amount = f"₹{amount:,}"

        # A retry has no payment link by design.  Its message must say so rather
        # than fabricating a URL that has not been created by the provider.
        if not link_url:
            if language == "Hinglish":
                return f"Hi {first_name}, hum aapka {formatted_amount} payment safely retry kar rahe hain. Koi issue ho toh reply karein. — RecoverX"
            return f"Hi {first_name}, we are safely retrying your {formatted_amount} payment. Reply if you need assistance. — RecoverX"

        if language == "Hinglish":
            return (
                f"Hi {first_name} 👋\n\n"
                f"Aapka {formatted_amount} payment complete nahi ho paya.\n\n"
                f"Aap neeche diye secure link se turant payment complete kar sakte hain:\n"
                f"{link_url}\n\n"
                f"Agar koi issue hai toh reply karein. — RecoverX"
            )
        else:
            return (
                f"Hi {first_name} 👋\n\n"
                f"Your payment of {formatted_amount} could not be completed.\n\n"
                f"You can securely complete your payment using the link below:\n"
                f"{link_url}\n\n"
                f"Need assistance? Reply to this message. — RecoverX"
            )

    def _add_audit(
        self,
        session: Session,
        org_id: str,
        case_id: str | None,
        actor: str,
        event_name: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        event = AuditEvent(
            id=str(uuid4()),
            organization_id=org_id,
            case_id=case_id,
            actor=actor,
            event_name=event_name,
            payload=payload,
            correlation_id=correlation_id,
        )
        session.add(event)


# Global singleton instance
default_gateway = ToolGateway()
