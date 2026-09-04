# Workflows

Cases move from actionable to waiting for payment, recovered, promise-to-pay, escalated, stopped, or expired. The in-process runner remains the default local fallback.

## Temporal mode

Set `TEMPORAL_ENABLED=true` to dispatch approved recovery actions and Promise-to-Pay checks to Temporal. The worker runs `app.workflows.temporal_worker`, using the `TEMPORAL_TASK_QUEUE` queue. Recovery waits two days before its first follow-up and three additional days before escalation; activities reopen their own SQLAlchemy session and commit or roll back atomically.

Required settings are `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, and `TEMPORAL_TASK_QUEUE`. `TEMPORAL_API_KEY` is optional for local Temporal and should be supplied through the deployment secret store for Temporal Cloud.