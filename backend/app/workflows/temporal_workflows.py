"""Durable Temporal workflows for multi-day RecoverX recovery."""
from datetime import datetime, timedelta, timezone
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .temporal_activities import execute_recovery_step, evaluate_promise_commitment, get_promise_due_at


_ACTIVITY_TIMEOUT = timedelta(seconds=45)
_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name="RecoverXRecoveryWorkflow")
class RecoverXRecoveryWorkflow:
    @workflow.run
    async def run(self, case_id: str) -> dict[str, Any]:
        result = await workflow.execute_activity(
            execute_recovery_step,
            args=[case_id, 0],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
        if result.get("status") != "WAITING_FOR_PAYMENT":
            return result

        await workflow.sleep(timedelta(days=2))
        result = await workflow.execute_activity(
            execute_recovery_step,
            args=[case_id, 2],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
        if result.get("status") != "FOLLOWUP_DISPATCHED":
            return result

        await workflow.sleep(timedelta(days=3))
        return await workflow.execute_activity(
            execute_recovery_step,
            args=[case_id, 3],
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )


@workflow.defn(name="RecoverXPromiseToPayWorkflow")
class RecoverXPromiseToPayWorkflow:
    @workflow.run
    async def run(self, promise_id: str) -> dict[str, Any]:
        due_at = await workflow.execute_activity(
            get_promise_due_at,
            promise_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
        if due_at:
            due = datetime.fromisoformat(due_at)
            now = workflow.now()
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due > now:
                await workflow.sleep(due - now)
        return await workflow.execute_activity(
            evaluate_promise_commitment,
            promise_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_RETRY_POLICY,
        )
