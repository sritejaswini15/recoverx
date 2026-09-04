"""Deterministic Revenue Risk Engine for RecoverX.
Calculates risk score (0-100), recovery probability (0.0-1.0), and expected recovery value.
Never allows LLM to calculate or alter financial amounts.
"""
from dataclasses import dataclass
from typing import Any
from app.db import Customer


@dataclass(frozen=True)
class RiskResult:
    risk_score: int
    recovery_probability: float
    expected_recovery_value: int
    model_version: str
    factors: dict[str, Any]


class RiskEngine:
    """Deterministic financial calculations combining customer reliability, failure history,
    aging, and transaction characteristics.
    """

    MODEL_VERSION = "deterministic-v2.0"

    @classmethod
    def evaluate(
        cls,
        amount: int,
        customer: Customer | None,
        overdue_days: int = 0,
        repeat_failures: int = 0,
        event_type: str = "PAYMENT_FAILURE",
    ) -> RiskResult:
        reliability = customer.payment_reliability_pct if customer else 70.0
        hist_recovery = customer.historical_recovery_rate if customer else 0.5
        successful_payments = customer.successful_payments if customer else 5
        failed_payments = customer.failed_payments if customer else 1

        total_txns = max(1, successful_payments + failed_payments)
        success_ratio = round(successful_payments / total_txns, 2)

        # 1. Calculate Risk Score (0 - 100)
        # Higher score means higher revenue risk / severity
        # Factors: Amount scale, days overdue, repeat failures, customer unreliability
        amount_factor = min(35.0, (amount / 3000.0))  # e.g., ₹25,000 = 8.3, ₹100,000 = 33
        unreliability_factor = (100.0 - reliability) * 0.35  # e.g., 90% rel -> 3.5, 60% rel -> 14
        overdue_factor = min(25.0, overdue_days * 1.5)  # e.g. 7 days -> 10.5
        repeat_failure_factor = min(20.0, repeat_failures * 6.0)

        raw_risk = amount_factor + unreliability_factor + overdue_factor + repeat_failure_factor + 15.0
        risk_score = max(5, min(99, round(raw_risk)))

        # 2. Calculate Recovery Probability (0.0 - 1.0)
        # Baseline probability from customer reliability & historical recovery
        base_prob = 0.40 + (reliability / 200.0)  # 90% rel -> 0.85; 60% rel -> 0.70
        hist_bonus = (hist_recovery - 0.5) * 0.15
        overdue_penalty = overdue_days * 0.015
        failure_penalty = repeat_failures * 0.08
        amount_penalty = min(0.12, (amount / 250000.0))

        # Event type adjustments
        event_bonus = 0.0
        if event_type == "CHECKOUT_ABANDONED":
            event_bonus = -0.05  # Abandonments slightly harder than technical payment failures
        elif event_type == "SUBSCRIPTION_HALTED":
            event_bonus = 0.04  # Subscribed customers often update card quickly

        calc_prob = base_prob + hist_bonus - overdue_penalty - failure_penalty - amount_penalty + event_bonus
        # Bounded between 0.15 and 0.96
        recovery_probability = max(0.15, min(0.96, round(calc_prob, 2)))

        # 3. Expected Recovery Value = Amount * Recovery Probability
        expected_recovery_value = round(amount * recovery_probability)

        factors = {
            "amount": amount,
            "reliability_pct": reliability,
            "success_ratio": success_ratio,
            "historical_recovery_rate": hist_recovery,
            "overdue_days": overdue_days,
            "repeat_failures": repeat_failures,
            "event_type": event_type,
            "amount_factor": round(amount_factor, 1),
            "unreliability_factor": round(unreliability_factor, 1),
            "overdue_factor": round(overdue_factor, 1),
            "repeat_failure_factor": round(repeat_failure_factor, 1),
        }

        return RiskResult(
            risk_score=risk_score,
            recovery_probability=recovery_probability,
            expected_recovery_value=expected_recovery_value,
            model_version=cls.MODEL_VERSION,
            factors=factors,
        )
