"""Resilient Workflow Runner.
Dispatches durable workflows to Temporal when configured, or executes through resilient in-process runner.
"""
from typing import Any
from sqlalchemy.orm import Session
from app.core.config import settings
from .recovery_workflow import RecoveryWorkflow
from .promise_workflow import PromiseToPayWorkflow


class WorkflowRunner:
    @staticmethod
    def trigger_recovery_workflow(session: Session, case_id: str, fast_forward_days: int = 0) -> dict[str, Any]:
        if settings.TEMPORAL_ENABLED:
            from .temporal_client import start_recovery_workflow

            try:
                return start_recovery_workflow(case_id)
            except Exception as exc:
                return {"status": "DISPATCH_FAILED", "workflow_id": None, "error": str(exc)}
        workflow = RecoveryWorkflow(case_id, session)
        return workflow.execute_step(simulated_fast_forward_days=fast_forward_days)

    @staticmethod
    def trigger_promise_workflow(session: Session, promise_id: str) -> dict[str, Any]:
        if settings.TEMPORAL_ENABLED:
            from .temporal_client import start_promise_workflow

            try:
                return start_promise_workflow(promise_id)
            except Exception as exc:
                return {"status": "DISPATCH_FAILED", "workflow_id": None, "error": str(exc)}
        workflow = PromiseToPayWorkflow(promise_id, session)
        return workflow.evaluate_commitment()


workflow_runner = WorkflowRunner()
