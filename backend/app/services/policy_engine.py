"""Deterministic Policy & Guardrails Engine for RecoverX.
Evaluates merchant constraints before any recovery action or payment operation is authorized.
"""
from dataclasses import dataclass
from typing import Literal

from app.db import Customer, Policy, RecoveryCase

PolicyDecision = Literal["AUTO_APPROVE", "HUMAN_REVIEW", "STOP"]


@dataclass(frozen=True)
class PolicyEvaluationResult:
    decision: PolicyDecision
    reasons: list[str]
    rule_violations: list[str]
    max_amount_limit: int
    min_confidence_limit: float
    current_attempts: int
    max_attempts_limit: int


class PolicyEngine:
    @classmethod
    def evaluate(
        cls,
        policy: Policy,
        case: RecoveryCase,
        customer: Customer | None,
        ai_confidence: float | None = None,
        overdue_days: int = 0,
    ) -> PolicyEvaluationResult:
        reasons: list[str] = []
        violations: list[str] = []
        confidence = ai_confidence if ai_confidence is not None else case.ai_confidence

        # 1. Check Opt-Out
        if customer and customer.opted_out:
            reasons.append("Customer has explicitly opted out of communications")
            violations.append("CUSTOMER_OPTED_OUT")
            return PolicyEvaluationResult(
                decision="STOP",
                reasons=reasons,
                rule_violations=violations,
                max_amount_limit=policy.max_auto_action_amount,
                min_confidence_limit=policy.min_ai_confidence,
                current_attempts=case.contact_attempts,
                max_attempts_limit=policy.max_contact_attempts,
            )

        # 2. Check Terminal or Inactive States
        if case.status in ("RECOVERED", "STOPPED", "EXPIRED"):
            reasons.append(f"Case is already in terminal state: {case.status}")
            violations.append("CASE_ALREADY_TERMINATED")
            return PolicyEvaluationResult(
                decision="STOP",
                reasons=reasons,
                rule_violations=violations,
                max_amount_limit=policy.max_auto_action_amount,
                min_confidence_limit=policy.min_ai_confidence,
                current_attempts=case.contact_attempts,
                max_attempts_limit=policy.max_contact_attempts,
            )

        # 3. Check Contact Attempts
        if case.contact_attempts >= policy.max_contact_attempts:
            reasons.append(
                f"Maximum contact attempts reached ({case.contact_attempts}/{policy.max_contact_attempts})"
            )
            violations.append("MAX_ATTEMPTS_EXCEEDED")
            return PolicyEvaluationResult(
                decision="STOP",
                reasons=reasons,
                rule_violations=violations,
                max_amount_limit=policy.max_auto_action_amount,
                min_confidence_limit=policy.min_ai_confidence,
                current_attempts=case.contact_attempts,
                max_attempts_limit=policy.max_contact_attempts,
            )

        # 4. Check Amount Thresholds (Human Review)
        human_review_required = False
        amount_limit = min(policy.max_auto_action_amount, policy.human_approval_above_amount)
        if case.amount > amount_limit:
            reasons.append(
                f"Amount ₹{case.amount:,} exceeds auto-action limit of ₹{amount_limit:,}"
            )
            violations.append("AMOUNT_EXCEEDS_AUTO_LIMIT")
            human_review_required = True
        else:
            reasons.append(f"Amount ₹{case.amount:,} is within auto-action limit of ₹{amount_limit:,}")

        # 5. Check AI Confidence (Human Review)
        if confidence < policy.min_ai_confidence:
            reasons.append(
                f"AI confidence ({int(confidence * 100)}%) is below required threshold ({int(policy.min_ai_confidence * 100)}%)"
            )
            violations.append("LOW_AI_CONFIDENCE")
            human_review_required = True
        else:
            reasons.append(
                f"AI confidence ({int(confidence * 100)}%) meets threshold ({int(policy.min_ai_confidence * 100)}%)"
            )

        # 6. Check Aging / Overdue Days (Human Review)
        if overdue_days > policy.escalate_after_days:
            reasons.append(
                f"Case overdue duration ({overdue_days} days) exceeds escalation threshold ({policy.escalate_after_days} days)"
            )
            violations.append("OVERDUE_DAYS_EXCEEDED")
            human_review_required = True

        if human_review_required:
            return PolicyEvaluationResult(
                decision="HUMAN_REVIEW",
                reasons=reasons,
                rule_violations=violations,
                max_amount_limit=amount_limit,
                min_confidence_limit=policy.min_ai_confidence,
                current_attempts=case.contact_attempts,
                max_attempts_limit=policy.max_contact_attempts,
            )

        reasons.append("All policy guardrails satisfied. Action approved for autonomous execution.")
        return PolicyEvaluationResult(
            decision="AUTO_APPROVE",
            reasons=reasons,
            rule_violations=[],
            max_amount_limit=amount_limit,
            min_confidence_limit=policy.min_ai_confidence,
            current_attempts=case.contact_attempts,
            max_attempts_limit=policy.max_contact_attempts,
        )
