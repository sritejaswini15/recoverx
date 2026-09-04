"""Analytics Service for RecoverX.
Aggregates real-time financial metrics, funnel conversion, and strategy performance from PostgreSQL.
"""
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Experiment, ExperimentResult, RecoveryAction, RecoveryCase, RevenueEvent


class AnalyticsService:
    @staticmethod
    def get_recovery_analytics(session: Session, organization_id: str | None = None) -> dict[str, Any]:
        query = select(RecoveryCase)
        if organization_id:
            query = query.where(RecoveryCase.organization_id == organization_id)
        cases = session.scalars(query).all()
        if not cases:
            return {
                "revenue_at_risk": 0,
                "revenue_targeted": 0,
                "revenue_recovered": 0,
                "recovery_rate": 0.0,
                "expected_recovery_value": 0,
                "cases": 0,
                "successful_recoveries": 0,
                "escalations": 0,
                "stopped_cases": 0,
                "average_recovery_time_hours": 0.0,
                "funnel": {
                    "risk_cases": 0,
                    "eligible": 0,
                    "actions": 0,
                    "successful": 0,
                },
                "mode": "simulation",
            }

        at_risk = sum(case.amount for case in cases)
        recovered = sum(case.recovered_amount for case in cases)
        targeted = sum(
            case.risk_assessment.expected_recovery_value
            for case in cases
            if case.policy_decision != "STOP" and case.risk_assessment
        )
        expected_total = sum(
            case.risk_assessment.expected_recovery_value
            for case in cases
            if case.risk_assessment
        )

        eligible = sum(1 for case in cases if case.policy_decision != "STOP")
        actions = sum(1 for case in cases if case.action_executed)
        successful = sum(1 for case in cases if case.status == "RECOVERED")
        escalations = sum(1 for case in cases if case.status == "ESCALATED")
        stopped = sum(1 for case in cases if case.status == "STOPPED")

        recovery_rate = round(recovered / at_risk, 4) if at_risk else 0.0
        recovery_hours = [
            max(
                0.0,
                (
                    (case.updated_at.replace(tzinfo=timezone.utc) if case.updated_at.tzinfo is None else case.updated_at)
                    - (case.created_at.replace(tzinfo=timezone.utc) if case.created_at.tzinfo is None else case.created_at)
                ).total_seconds() / 3600,
            )
            for case in cases
            if case.status == "RECOVERED" and case.updated_at and case.created_at
        ]

        return {
            "revenue_at_risk": at_risk,
            "revenue_targeted": targeted,
            "revenue_recovered": recovered,
            "recovery_rate": recovery_rate,
            "expected_recovery_value": expected_total,
            "cases": len(cases),
            "successful_recoveries": successful,
            "escalations": escalations,
            "stopped_cases": stopped,
            "average_recovery_time_hours": round(sum(recovery_hours) / len(recovery_hours), 2) if recovery_hours else 0.0,
            "funnel": {
                "risk_cases": len(cases),
                "eligible": eligible,
                "actions": actions,
                "successful": successful,
            },
            "mode": "simulation",
        }

    @staticmethod
    def get_strategy_performance(session: Session, organization_id: str | None = None) -> list[dict[str, Any]]:
        query = select(RecoveryCase)
        if organization_id:
            query = query.where(RecoveryCase.organization_id == organization_id)
        cases = session.scalars(query).all()
        action_rows = session.scalars(
            select(RecoveryAction)
            .join(RecoveryCase)
            .where(RecoveryCase.organization_id == organization_id if organization_id else True)
        ).all()
        actions = sorted({action.action_type for action in action_rows} | {case.recommended_action for case in cases})
        results = []

        for action in actions:
            action_rows_for_type = [row for row in action_rows if row.action_type == action]
            action_case_ids = {row.recovery_case_id for row in action_rows_for_type}
            action_cases = [c for c in cases if c.id in action_case_ids]
            if not action_cases and not action_rows_for_type:
                action_cases = [c for c in cases if c.recommended_action == action]
            attempts = len(action_rows_for_type) or len(action_cases)
            success = sum(1 for c in action_cases if c.status == "RECOVERED")
            recovered_amount = sum(c.recovered_amount for c in action_cases)
            conv_rate = round(success / attempts, 4) if attempts else 0.0
            action_recovery_hours = [
                max(
                    0.0,
                    (
                        (c.updated_at.replace(tzinfo=timezone.utc) if c.updated_at.tzinfo is None else c.updated_at)
                        - (c.created_at.replace(tzinfo=timezone.utc) if c.created_at.tzinfo is None else c.created_at)
                    ).total_seconds() / 3600,
                )
                for c in action_cases
                if c.status == "RECOVERED" and c.updated_at and c.created_at
            ]

            results.append({
                "strategy": action,
                "attempts": attempts,
                "success": success,
                "recovery_rate": conv_rate,
                "recovered": recovered_amount,
                "average_recovery_time": round(sum(action_recovery_hours) / len(action_recovery_hours), 2) if action_recovery_hours else 0.0,
            })

        return results

    @staticmethod
    def get_experiments(session: Session, organization_id: str | None = None) -> list[dict[str, Any]]:
        query = select(Experiment)
        if organization_id:
            query = query.where(Experiment.organization_id == organization_id)
        experiments = session.scalars(query).all()
        data = []

        for exp in experiments:
            results = session.scalars(select(ExperimentResult).where(ExperimentResult.experiment_id == exp.id)).all()

            variants: dict[str, dict[str, Any]] = {}
            for r in results:
                if r.variant not in variants:
                    variants[r.variant] = {"attempts": 0, "recoveries": 0, "revenue": 0}
                variants[r.variant]["attempts"] += 1
                if r.outcome == "RECOVERED":
                    variants[r.variant]["recoveries"] += 1
                    variants[r.variant]["revenue"] += r.revenue

            variant_list = []
            for v_name, v_data in variants.items():
                rate = round(v_data["recoveries"] / v_data["attempts"], 4) if v_data["attempts"] else 0.0
                variant_list.append({
                    "variant": v_name,
                    "attempts": v_data["attempts"],
                    "recoveries": v_data["recoveries"],
                    "recovery_rate": rate,
                    "revenue_recovered": v_data["revenue"],
                })

            data.append({
                "id": exp.id,
                "name": exp.name,
                "segment": exp.segment,
                "status": exp.status,
                "variants": variant_list,
            })

        return data
