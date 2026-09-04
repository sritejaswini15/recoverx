"""Run the RecoverX Temporal worker.

Start with TEMPORAL_ENABLED=true and a reachable Temporal server.
"""
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import settings
from .temporal_activities import evaluate_promise_commitment, execute_recovery_step, get_promise_due_at
from .temporal_workflows import RecoverXPromiseToPayWorkflow, RecoverXRecoveryWorkflow


async def run_worker() -> None:
    client = await Client.connect(
        settings.TEMPORAL_HOST,
        namespace=settings.TEMPORAL_NAMESPACE,
        api_key=settings.TEMPORAL_API_KEY,
    )
    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[RecoverXRecoveryWorkflow, RecoverXPromiseToPayWorkflow],
        activities=[execute_recovery_step, evaluate_promise_commitment, get_promise_due_at],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
