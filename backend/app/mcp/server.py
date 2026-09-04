"""RecoverX Model Context Protocol (MCP) Server.
Mandatory first-class RecoverX interface exposing controlled read and write tools.
Enforces strict Tool Gateway + Policy Engine boundary for all write actions.
"""
from datetime import datetime, timezone
from typing import Any, Callable, Dict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import (
    AuditEvent,
    Customer,
    Payment,
    PaymentAttempt,
    PaymentLink,
    Policy,
    RecoveryCase,
    RiskAssessment,
)
from app.services.policy_engine import PolicyEngine
from app.services.tool_gateway import default_gateway


class MCPServer:
    """First-class Model Context Protocol server exposing read & write capabilities for RecoverX."""

    def __init__(self) -> None:
        self.read_tools: Dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {}
        self.write_tools: Dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        # READ TOOLS
        self.read_tools["get_recovery_case"] = self._get_recovery_case
        self.read_tools["list_recovery_cases"] = self._list_recovery_cases
        self.read_tools["get_customer_context"] = self._get_customer_context
        self.read_tools["get_payment_history"] = self._get_payment_history
        self.read_tools["get_risk_assessment"] = self._get_risk_assessment
        self.read_tools["get_recovery_recommendation"] = self._get_recovery_recommendation
        self.read_tools["evaluate_policy"] = self._evaluate_policy
        self.read_tools["get_recovery_status"] = self._get_recovery_status
        self.read_tools["get_analytics"] = self._get_analytics
        self.read_tools["get_audit_history"] = self._get_audit_history

        # WRITE TOOLS (Strictly pass through Policy Engine + Tool Gateway)
        self.write_tools["retry_payment"] = self._retry_payment
        self.write_tools["create_payment_link"] = self._create_payment_link
        self.write_tools["send_recovery_message"] = self._send_recovery_message
        self.write_tools["create_escalation"] = self._create_escalation
        self.write_tools["record_promise_to_pay"] = self._record_promise_to_pay

    def list_tools(self) -> list[dict[str, Any]]:
        """Returns tool definitions adhering to Model Context Protocol specification."""
        tools = []
        for name in self.read_tools:
            tools.append({
                "name": name,
                "type": "read",
                "description": f"RecoverX read tool: {name.replace('_', ' ')}",
            })
        for name in self.write_tools:
            tools.append({
                "name": name,
                "type": "write",
                "description": f"RecoverX controlled write tool: {name.replace('_', ' ')}. Passes through Policy Engine and Tool Gateway.",
            })
        return tools

    def call_tool(
        self,
        session: Session,
        name: str,
        arguments: dict[str, Any],
        actor: str = "mcp_client",
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        """Executes an MCP tool with audit logging and policy boundary enforcement."""
        self._assert_tenant(session, arguments, organization_id)
        arguments["_organization_id"] = organization_id
        if name in self.read_tools:
            return self.read_tools[name](session, arguments)
        elif name in self.write_tools:
            arguments["_actor"] = actor
            return self.write_tools[name](session, arguments)
        else:
            raise ValueError(f"Unknown MCP tool: {name}")

    @staticmethod
    def _assert_tenant(session: Session, args: dict[str, Any], organization_id: str | None) -> None:
        if not organization_id:
            return
        case_id = args.get("case_id")
        if case_id and not session.scalar(
            select(RecoveryCase).where(RecoveryCase.id == case_id, RecoveryCase.organization_id == organization_id)
        ):
            raise ValueError("Recovery case not found")
        customer_id = args.get("customer_id")
        if customer_id and not session.scalar(
            select(Customer).where(Customer.id == customer_id, Customer.organization_id == organization_id)
        ):
            raise ValueError("Customer not found")

    # --- READ IMPLEMENTATIONS ---

    def _get_recovery_case(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found", "case_id": case_id}
        return {
            "id": case.id,
            "customer_id": case.customer_id,
            "customer_name": case.customer.name,
            "amount": case.amount,
            "currency": case.currency,
            "status": case.status,
            "risk_score": case.risk_assessment.risk_score,
            "recovery_probability": case.risk_assessment.recovery_probability,
            "expected_recovery_value": case.risk_assessment.expected_recovery_value,
            "recommended_action": case.recommended_action,
            "policy_decision": case.policy_decision,
            "ai_confidence": case.ai_confidence,
            "contact_attempts": case.contact_attempts,
            "recovered_amount": case.recovered_amount,
            "action_executed": case.action_executed,
            "created_at": case.created_at.isoformat(),
        }

    def _list_recovery_cases(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(100, int(args.get("limit", 20)))
        status = args.get("status")
        query = select(RecoveryCase)
        if args.get("_organization_id"):
            query = query.where(RecoveryCase.organization_id == args["_organization_id"])
        if status:
            query = query.where(RecoveryCase.status == status.upper())
        cases = session.scalars(query.limit(limit)).all()
        return {
            "count": len(cases),
            "items": [
                {
                    "id": c.id,
                    "customer": c.customer.name,
                    "amount": c.amount,
                    "status": c.status,
                    "risk_score": c.risk_assessment.risk_score,
                    "expected_recovery": c.risk_assessment.expected_recovery_value,
                }
                for c in cases
            ],
        }

    def _get_customer_context(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        customer_id = args.get("customer_id")
        customer = session.get(Customer, customer_id)
        if not customer:
            return {"error": "Customer not found"}
        return {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "lifetime_value": customer.lifetime_value,
            "payment_reliability_pct": customer.payment_reliability_pct,
            "successful_payments": customer.successful_payments,
            "failed_payments": customer.failed_payments,
            "preferred_channel": customer.preferred_channel,
            "preferred_language": customer.preferred_language,
            "historical_recovery_rate": customer.historical_recovery_rate,
            "opted_out": customer.opted_out,
        }

    def _get_payment_history(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        customer_id = args.get("customer_id")
        payments = session.scalars(
            select(Payment).where(Payment.customer_id == customer_id).order_by(Payment.created_at.desc()).limit(10)
        ).all()
        return {
            "customer_id": customer_id,
            "payments": [
                {
                    "id": p.provider_payment_id,
                    "amount": p.amount,
                    "status": p.status,
                    "failure_reason": p.failure_reason,
                    "created_at": p.created_at.isoformat(),
                }
                for p in payments
            ],
        }

    def _get_risk_assessment(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case or not case.risk_assessment:
            return {"error": "Risk assessment not found"}
        risk = case.risk_assessment
        return {
            "case_id": case.id,
            "risk_score": risk.risk_score,
            "recovery_probability": risk.recovery_probability,
            "expected_recovery_value": risk.expected_recovery_value,
            "factors": risk.factors,
            "model_version": risk.model_version,
        }

    def _get_recovery_recommendation(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found"}
        return {
            "case_id": case.id,
            "recommended_action": case.recommended_action,
            "ai_confidence": case.ai_confidence,
            "policy_decision": case.policy_decision,
            "status": case.status,
        }

    def _evaluate_policy(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found"}
        policy = session.scalar(select(Policy).where(Policy.organization_id == case.organization_id))
        if not policy:
            return {"error": "Policy not found"}
        customer = session.get(Customer, case.customer_id)
        result = PolicyEngine.evaluate(policy, case, customer)
        return {
            "decision": result.decision,
            "reasons": result.reasons,
            "violations": result.rule_violations,
        }

    def _get_recovery_status(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found"}
        link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case.id))
        return {
            "case_id": case.id,
            "case_status": case.status,
            "recovered_amount": case.recovered_amount,
            "payment_link_status": link.status if link else None,
            "contact_attempts": case.contact_attempts,
        }

    def _get_analytics(self, session: Session, _args: dict[str, Any]) -> dict[str, Any]:
        query = select(RecoveryCase)
        if _args.get("_organization_id"):
            query = query.where(RecoveryCase.organization_id == _args["_organization_id"])
        cases = session.scalars(query).all()
        at_risk = sum(c.amount for c in cases)
        recovered = sum(c.recovered_amount for c in cases)
        successful = sum(1 for c in cases if c.status == "RECOVERED")
        return {
            "revenue_at_risk": at_risk,
            "revenue_recovered": recovered,
            "recovery_rate": round(recovered / at_risk, 4) if at_risk else 0.0,
            "cases_processed": len(cases),
            "successful_recoveries": successful,
        }

    def _get_audit_history(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(25)
        if args.get("_organization_id"):
            query = query.where(AuditEvent.organization_id == args["_organization_id"])
        if case_id:
            query = query.where(AuditEvent.case_id == case_id)
        events = session.scalars(query).all()
        return {
            "events": [
                {
                    "event_name": e.event_name,
                    "case_id": e.case_id,
                    "actor": e.actor,
                    "payload": e.payload,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ]
        }

    # --- WRITE IMPLEMENTATIONS (Through Tool Gateway & Policy Engine) ---

    def _retry_payment(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found"}
        actor = args.get("_actor", "mcp_client")
        action = default_gateway.execute_recovery_action(session, case, "PAYMENT_RETRY", actor=actor, organization_id=args.get("_organization_id"))
        return {"action_id": action.id, "status": action.status, "case_id": case.id}

    def _create_payment_link(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found"}
        actor = args.get("_actor", "mcp_client")
        action = default_gateway.execute_recovery_action(session, case, "PAYMENT_LINK", actor=actor, organization_id=args.get("_organization_id"))
        link = session.scalar(select(PaymentLink).where(PaymentLink.case_id == case.id))
        return {
            "action_id": action.id,
            "status": action.status,
            "case_id": case.id,
            "link_id": link.provider_link_id if link else None,
            "short_url": link.short_url if link else None,
        }

    def _send_recovery_message(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        case = session.get(RecoveryCase, case_id)
        if not case:
            return {"error": "Case not found"}
        actor = args.get("_actor", "mcp_client")
        action = default_gateway.execute_recovery_action(session, case, "PERSONALIZED_OUTREACH", actor=actor, organization_id=args.get("_organization_id"))
        return {"action_id": action.id, "status": action.status, "case_id": case.id}

    def _create_escalation(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        reason = args.get("reason", "MCP_OPERATOR_REQUEST")
        notes = args.get("notes")
        actor = args.get("_actor", "mcp_client")
        escalation = default_gateway.create_escalation(session, case_id, reason, notes=notes, actor=actor)
        return {"escalation_id": escalation.id, "case_id": case_id, "status": "ESCALATED"}

    def _record_promise_to_pay(self, session: Session, args: dict[str, Any]) -> dict[str, Any]:
        case_id = args.get("case_id")
        amount = int(args.get("amount", 0))
        date_str = args.get("promised_date")
        promised_date = datetime.fromisoformat(date_str) if date_str else datetime.now(timezone.utc)
        notes = args.get("notes")
        actor = args.get("_actor", "mcp_client")
        promise = default_gateway.record_promise_to_pay(session, case_id, amount, promised_date, notes=notes, actor=actor)
        return {"promise_id": promise.id, "case_id": case_id, "status": promise.status}


mcp_server = MCPServer()
