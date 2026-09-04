"""Temporal activities for RecoverX durable workflows."""
from datetime import datetime
from typing import Any

from temporalio import activity

from app.db import PromiseToPay, SessionLocal
from sqlalchemy import select
from app.workflows.promise_workflow import PromiseToPayWorkflow
from app.workflows.recovery_workflow import RecoveryWorkflow


@activity.defn(name="execute_recovery_step")
def execute_recovery_step(case_id: str, fast_forward_days: int = 0) -> dict[str, Any]:
    session = SessionLocal()
    try:
        result = RecoveryWorkflow(case_id, session).execute_step(
            simulated_fast_forward_days=fast_forward_days
        )
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@activity.defn(name="evaluate_promise_commitment")
def evaluate_promise_commitment(promise_id: str) -> dict[str, Any]:
    session = SessionLocal()
    try:
        result = PromiseToPayWorkflow(promise_id, session).evaluate_commitment()
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@activity.defn(name="get_promise_due_at")
def get_promise_due_at(promise_id: str) -> str | None:
    session = SessionLocal()
    try:
        promise = session.scalar(select(PromiseToPay).where(PromiseToPay.id == promise_id))
        return promise.promised_date.isoformat() if promise else None
    finally:
        session.close()
