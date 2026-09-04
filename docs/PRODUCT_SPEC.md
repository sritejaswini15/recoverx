# RecoverX Product Spec

RecoverX is an AI revenue recovery control plane for Razorpay merchants. Razorpay or the simulated provider remains the payment source of truth; RecoverX owns detection, prioritization, diagnosis, policy, execution, observation, and measurement.

Supported revenue leaks are payment failures, recurring payment failures, overdue invoices, and checkout or Payment Link abandonment. Financial amounts are persisted in the backend and are never supplied by the frontend or invented by AI.