# Testing

Run backend tests with `python -m pytest tests -q` from `backend`. The current regression suite covers canonical normalization, deterministic risk math, opt-out policy stops, amount-based human review, webhook verification, deduplication, tenant isolation, analytics, and integration status.

For the frontend, run `npm.cmd run lint` and `npm.cmd run build` from `frontend`. The production build validates all operational routes, including the customer payment experience. The live smoke path should verify login, case detail, execute, simulated payment, recovered state, and duplicate signed webhook behavior.
