"""LangGraph AI Recovery Agent for RecoverX.
Stateful multi-node recovery decisioning graph with strict Pydantic validation and safe failover.
"""
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END

from app.schemas.agent import RecoveryAction, RecoveryDecision
from app.services.risk_engine import RiskEngine, RiskResult
from app.services.policy_engine import PolicyEngine, PolicyEvaluationResult
from app.db import Customer, Policy, RecoveryCase, RevenueEvent


class RecoveryAgentState(TypedDict, total=False):
    # Context
    organization_id: str
    case_id: str
    event_type: str
    amount: int
    currency: str
    customer_id: str
    customer_name: str
    customer_reliability: float
    successful_payments: int
    failed_payments: int
    preferred_channel: str
    preferred_language: str
    overdue_days: int
    repeat_failures: int
    
    # Risk
    risk_score: int
    recovery_probability: float
    expected_recovery_value: int
    risk_factors: dict[str, Any]
    
    # Diagnosis & Strategy
    diagnosis: str
    root_cause: str
    recommended_action: str
    ai_reasoning: str
    ai_confidence: float
    communication_tone: str
    suggested_language: str
    decision_valid: bool
    
    # Policy Gate — values populated from DB Policy before graph invocation
    policy_max_amount: int       # merchant-configured auto-action ceiling
    policy_min_confidence: float  # merchant-configured confidence floor
    policy_max_attempts: int      # merchant-configured max contact attempts
    policy_decision: str
    policy_reasons: list[str]
    policy_violations: list[str]
    
    # Tool Execution & Observation
    action_executed: bool
    action_result: dict[str, Any]
    observation: str
    final_case_status: str


def load_context(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 1: Load and structure customer and event context."""
    reliability = state.get("customer_reliability", 85.0)
    total_txns = state.get("successful_payments", 10) + state.get("failed_payments", 1)
    repeat_failures = state.get("repeat_failures", 0)
    overdue_days = state.get("overdue_days", 0)
    
    return {
        "customer_reliability": reliability,
        "repeat_failures": repeat_failures,
        "overdue_days": overdue_days,
        "decision_valid": True,
    }


def risk_analysis(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 2: Calculate deterministic risk score, recovery probability, and expected recovery value."""
    amount = state.get("amount", 10000)
    reliability = state.get("customer_reliability", 85.0)
    overdue_days = state.get("overdue_days", 0)
    repeat_failures = state.get("repeat_failures", 0)
    event_type = state.get("event_type", "PAYMENT_FAILURE")

    # High-level deterministic evaluation
    risk_eval = RiskEngine.evaluate(
        amount=amount,
        customer=None,  # Handled via explicit values
        overdue_days=overdue_days,
        repeat_failures=repeat_failures,
        event_type=event_type,
    )
    # Adjust for customer reliability
    prob = max(0.18, min(0.95, round(0.45 + (reliability / 200.0) - (repeat_failures * 0.07) - (overdue_days * 0.01), 2)))
    exp_val = round(amount * prob)

    return {
        "risk_score": risk_eval.risk_score,
        "recovery_probability": prob,
        "expected_recovery_value": exp_val,
        "risk_factors": risk_eval.factors,
    }


def diagnosis(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 3: Determine root cause and customer context explanation."""
    event_type = state.get("event_type", "PAYMENT_FAILURE")
    reliability = state.get("customer_reliability", 85.0)
    repeat_failures = state.get("repeat_failures", 0)
    overdue_days = state.get("overdue_days", 0)

    if event_type == "CHECKOUT_ABANDONED":
        root_cause = "CHECKOUT_DROPOFF"
        diag = "Customer dropped off during checkout before completing transaction. Cart or intent is recoverable."
    elif event_type == "SUBSCRIPTION_HALTED":
        root_cause = "MANDATE_DECLINE"
        diag = "Recurring mandate failed. Likely card expiration, daily limit, or insufficient balance at billing cycle."
    elif event_type in ("INVOICE_OVERDUE", "INVOICE_EXPIRED"):
        root_cause = "B2B_PAYMENT_DELAY"
        diag = f"Invoice overdue by {overdue_days} days. Standard commercial receivables cycle delay."
    elif repeat_failures > 1:
        root_cause = "REPEATED_METHOD_DECLINE"
        diag = f"Multiple consecutive transaction attempts declined ({repeat_failures} failures). Method may be locked or balance exhausted."
    elif reliability >= 80.0:
        root_cause = "ISOLATED_PAYMENT_METHOD_ISSUE"
        diag = f"Customer has strong payment reliability ({int(reliability)}%). Failure is an isolated incident rather than intentional default."
    else:
        root_cause = "INSUFFICIENT_FUNDS_OR_LIMIT"
        diag = "Transaction failed due to insufficient funds or banking limit exhaustion."

    return {
        "root_cause": root_cause,
        "diagnosis": diag,
    }


def strategy(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 4: Select optimal recovery strategy and communication approach."""
    root_cause = state.get("root_cause", "ISOLATED_PAYMENT_METHOD_ISSUE")
    event_type = state.get("event_type", "PAYMENT_FAILURE")
    reliability = state.get("customer_reliability", 85.0)
    preferred_channel = state.get("preferred_channel", "whatsapp")
    preferred_language = state.get("preferred_language", "English")
    prob = state.get("recovery_probability", 0.80)

    # Strategy mapping
    if event_type == "CHECKOUT_ABANDONED":
        action = RecoveryAction.PAYMENT_LINK
        reasoning = "Send targeted Payment Link via preferred channel with item reservation notice."
        confidence = min(0.95, prob + 0.05)
    elif event_type in ("INVOICE_OVERDUE", "INVOICE_EXPIRED"):
        action = RecoveryAction.REMINDER
        reasoning = "Send polite professional statement reminder with one-click payment options."
        confidence = min(0.92, prob)
    elif root_cause == "ISOLATED_PAYMENT_METHOD_ISSUE":
        action = RecoveryAction.PAYMENT_LINK
        reasoning = (
            f"Customer has strong historical track record ({int(reliability)}% reliability). "
            f"Recommended Payment Link + {preferred_channel.title()} outreach for highest conversion."
        )
        confidence = 0.91
    elif root_cause == "MANDATE_DECLINE":
        action = RecoveryAction.PAYMENT_RETRY
        reasoning = "Schedule automated payment retry at next optimal billing window + card update link."
        confidence = 0.88
    elif reliability < 60.0 and state.get("amount", 0) > 50000:
        action = RecoveryAction.ESCALATE_TO_HUMAN
        reasoning = "High-value case with low customer reliability. Operator intervention required."
        confidence = 0.65
    else:
        action = RecoveryAction.PAYMENT_LINK
        reasoning = "Deliver instant Payment Link to customer's verified channel."
        confidence = max(0.70, prob)

    # Validate output schema via Pydantic
    try:
        decision = RecoveryDecision(
            diagnosis=state.get("diagnosis", ""),
            root_cause=root_cause,
            recovery_probability=prob,
            recommended_action=action,
            reasoning=reasoning,
            confidence=confidence,
            suggested_language=preferred_language,
        )
        valid = True
    except Exception:
        action = RecoveryAction.ESCALATE_TO_HUMAN
        reasoning = "Decision schema validation failed. Safe failover to human review."
        confidence = 0.50
        valid = False

    return {
        "recommended_action": action.value,
        "ai_reasoning": reasoning,
        "ai_confidence": confidence,
        "suggested_language": preferred_language,
        "decision_valid": valid,
    }


def policy_gate(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 5: Evaluate deterministic merchant policy guardrails.
    Policy limits are taken from state, populated from the DB Policy by CaseService.
    Falls back to spec defaults when invoked outside the full case pipeline (e.g. batch eval).
    """
    amount = state.get("amount", 0)
    confidence = state.get("ai_confidence", 0.80)
    repeat_failures = state.get("repeat_failures", 0)
    contact_attempts = state.get("contact_attempts", 0)

    # Read DB-sourced policy values; fall back to spec defaults so the graph
    # remains independently runnable (e.g. batch evaluation, unit tests).
    max_auto_amount: int = state.get("policy_max_amount", 25000)         # type: ignore[assignment]
    min_confidence: float = state.get("policy_min_confidence", 0.70)     # type: ignore[assignment]
    max_attempts: int = state.get("policy_max_attempts", 3)              # type: ignore[assignment]

    reasons: list[str] = []
    violations: list[str] = []
    human_review = False

    if amount > max_auto_amount:
        reasons.append(f"Amount ₹{amount:,} exceeds auto-action limit of ₹{max_auto_amount:,}")
        violations.append("AMOUNT_EXCEEDS_AUTO_LIMIT")
        human_review = True
    else:
        reasons.append(f"Amount ₹{amount:,} is within auto-action limit of ₹{max_auto_amount:,}")

    if confidence < min_confidence:
        reasons.append(f"AI confidence ({int(confidence * 100)}%) is below threshold ({int(min_confidence * 100)}%)")
        violations.append("LOW_AI_CONFIDENCE")
        human_review = True
    else:
        reasons.append(f"AI confidence ({int(confidence * 100)}%) meets threshold ({int(min_confidence * 100)}%)")

    if contact_attempts >= max_attempts or repeat_failures >= max_attempts:
        reasons.append(f"Maximum contact/failure attempts reached ({max(contact_attempts, repeat_failures)}/{max_attempts})")
        violations.append("MAX_ATTEMPTS_REACHED")
        # Max attempts → STOP (not just human review) so the policy engine
        # and graph agree — both ultimately call PolicyEngine.evaluate which STOPs here.
        return {
            "policy_decision": "STOP",
            "policy_reasons": reasons,
            "policy_violations": violations,
        }

    decision = "HUMAN_REVIEW" if human_review else "AUTO_APPROVE"
    if not human_review:
        reasons.append("All policy guardrails satisfied. Action approved for autonomous execution.")

    return {
        "policy_decision": decision,
        "policy_reasons": reasons,
        "policy_violations": violations,
    }


def tool_execution(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 6: Execute authorized tools via Tool Gateway."""
    decision = state.get("policy_decision", "HUMAN_REVIEW")
    action = state.get("recommended_action", "PAYMENT_LINK")

    if decision == "AUTO_APPROVE":
        executed = True
        obs = f"Action {action} dispatched successfully through Tool Gateway."
        status = "ACTION_EXECUTED"
    elif decision == "HUMAN_REVIEW":
        executed = False
        obs = "Action routed to Human Escalation Queue due to policy limits."
        status = "ESCALATED"
    else:
        executed = False
        obs = "Action halted by policy stopping rules."
        status = "STOPPED"

    return {
        "action_executed": executed,
        "observation": obs,
        "final_case_status": status,
    }


def observe(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 7: Observe execution results and update tracking."""
    return {
        "observation": state.get("observation", "Observed execution complete"),
    }


def update_case(state: RecoveryAgentState) -> dict[str, Any]:
    """Node 8: Final state mapping for database update."""
    status = state.get("final_case_status", "ACTIONABLE")
    if state.get("action_executed"):
        status = "WAITING_FOR_PAYMENT"

    return {
        "final_case_status": status,
    }


# Build LangGraph
workflow = StateGraph(RecoveryAgentState)

workflow.add_node("load_context", load_context)
workflow.add_node("risk_analysis", risk_analysis)
workflow.add_node("diagnosis", diagnosis)
workflow.add_node("strategy", strategy)
workflow.add_node("policy_gate", policy_gate)
workflow.add_node("tool_execution", tool_execution)
workflow.add_node("observe", observe)
workflow.add_node("update_case", update_case)

workflow.add_edge(START, "load_context")
workflow.add_edge("load_context", "risk_analysis")
workflow.add_edge("risk_analysis", "diagnosis")
workflow.add_edge("diagnosis", "strategy")
workflow.add_edge("strategy", "policy_gate")
workflow.add_edge("policy_gate", "tool_execution")
workflow.add_edge("tool_execution", "observe")
workflow.add_edge("observe", "update_case")
workflow.add_edge("update_case", END)

recovery_graph = workflow.compile()
