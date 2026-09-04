# RecoverX — Definition of Done

*Golden Demo: 50-Step Complete Recovery Flow*

| # | Golden Demo Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Merchant login | COMPLETE | `/auth/login` with rate limiting; JWT token issued and stored in localStorage |
| 2 | Command Center | COMPLETE | `/` loads analytics, cases, strategies, audit from real backend |
| 3 | Real DB-backed metrics | COMPLETE | All metrics computed from PostgreSQL — no hardcoded values in frontend |
| 4 | Simulation Center | COMPLETE | `/simulation` and `/simulator` pages trigger all simulated scenarios |
| 5 | Simulated Razorpay payment failure | COMPLETE | `POST /simulation/event` with PAYMENT_FAILURE generates signed webhook |
| 6 | Webhook generated | COMPLETE | `SimulatedRazorpayProvider.generate_webhook()` creates HMAC-SHA256 signed payload |
| 7 | Signature verified | COMPLETE | `POST /webhooks/razorpay` verifies `x-razorpay-signature` before processing |
| 8 | Webhook deduplicated | COMPLETE | `WebhookReceipt` unique constraint on `(organization_id, provider_event_id)`; replay returns 200 with duplicate=true |
| 9 | Raw event persisted | COMPLETE | `WebhookReceipt.raw_payload` stores full body; `receipt.status` tracks processing state |
| 10 | Event normalized | COMPLETE | `event_normalizer.normalize_event()` produces `CanonicalRevenueEvent` with validated event_type, amount, source |
| 11 | Revenue Event created | COMPLETE | `RevenueEvent` row persisted with dedupe_key; idempotency at DB layer |
| 12 | Risk score generated | COMPLETE | `RiskEngine.evaluate()` produces `risk_score` (0-100), deterministic |
| 13 | Recovery probability generated | COMPLETE | `RiskEngine.evaluate()` produces `recovery_probability` (0.0-1.0) |
| 14 | Expected Recovery Value generated | COMPLETE | `RiskAssessment.expected_recovery_value = amount × probability` |
| 15 | Recovery Case created | COMPLETE | `RecoveryCase` row with `RC-XXXXXXXX` ID, organization-scoped |
| 16 | Customer profile/history available | COMPLETE | `Customer` model: lifetime_value, reliability_pct, successful_payments, failed_payments, preferences |
| 17 | LangGraph analysis | COMPLETE | 8-node StateGraph: load_context → risk_analysis → diagnosis → strategy → policy_gate → tool_execution → observe → update_case |
| 18 | Structured diagnosis | COMPLETE | `AgentDecision.diagnosis` and `root_cause` persisted; returned in case detail |
| 19 | Recovery strategy | COMPLETE | `recommended_action` from strategy node: PAYMENT_LINK, PAYMENT_RETRY, REMINDER, ESCALATE_TO_HUMAN |
| 20 | AI confidence | COMPLETE | `AgentDecision.confidence` persisted; used by policy gate |
| 21 | Policy evaluation | COMPLETE | `PolicyEngine.evaluate()` checks opt-out, terminal state, max attempts, amount, confidence, overdue days |
| 22 | Policy decision persisted | COMPLETE | `RecoveryCase.policy_decision` = AUTO_APPROVE / HUMAN_REVIEW / STOP; AuditEvent created |
| 23 | Tool Gateway | COMPLETE | `ToolGateway.execute_recovery_action()` is the sole path to financial/communication actions |
| 24 | Idempotency | COMPLETE | `RecoveryAction.idempotency_key = "action:{case_id}:{action_type}:{contact_attempts}"`; duplicate returns existing |
| 25 | MCP/provider interface | COMPLETE | `mcp/server.py` exposes 15 tools; all routed through Tool Gateway |
| 26 | Simulated Razorpay action | COMPLETE | `SimulatedRazorpayProvider` creates payment links, retries payments, generates confirmation webhooks |
| 27 | WhatsApp/email communication path | COMPLETE | `SimulatedWhatsAppProvider` and `SimulatedEmailProvider` send and log communications |
| 28 | Customer simulator | COMPLETE | `/simulator` page shows all cases, allows triggering events and simulating payment |
| 29 | Pay Now | COMPLETE | `POST /pay/{token}` public endpoint triggers payment webhook through full pipeline |
| 30 | Simulated Razorpay payment success | COMPLETE | `SimulatedRazorpayProvider.generate_webhook(event_type="payment_link.paid")` creates signed success payload |
| 31 | Success webhook | COMPLETE | `payment_link.paid` webhook processed by `/webhooks/razorpay` endpoint |
| 32 | RecoverX receives it | COMPLETE | Webhook pipeline accepts and routes the success event |
| 33 | Verify and deduplicate it | COMPLETE | Signature verified; dedupe_key prevents duplicate processing |
| 34 | Payment state updated | COMPLETE | `Payment.status = CAPTURED`; `PaymentLink.status = PAID` |
| 35 | Case becomes RECOVERED | COMPLETE | `RecoveryCase.status = RECOVERED`; `recovered_amount` updated |
| 36 | Workflow closes | COMPLETE | `workflow.closed` AuditEvent created; Temporal workflow completes or local runner marks closed |
| 37 | Consequential events audited | COMPLETE | `payment.recovered`, `workflow.closed`, all policy decisions, all tool executions logged to `audit_events` |
| 38 | Recovered revenue increases | COMPLETE | `RecoveryCase.recovered_amount` updated; `analytics/recovery` reflects new total |
| 39 | Recovery rate updates | COMPLETE | `AnalyticsService.get_recovery_analytics()` computes live from DB |
| 40 | Analytics updates | COMPLETE | All analytics endpoints compute from PostgreSQL in real time |
| 41 | Strategy performance updates | COMPLETE | `analytics/strategy-performance` aggregates by action_type |
| 42 | Case timeline shows complete process | COMPLETE | `GET /recovery-cases/{id}` returns diagnosis, decisions, communications, escalation, promises |
| 43 | Replay webhook does not duplicate state | COMPLETE | `WebhookReceipt` dedupe; `RevenueEvent.dedupe_key` unique constraint; returns existing state |
| 44 | Provider timeout is safely retried | COMPLETE | `POST /simulation/timeout` records retry attempt without duplicating actions |
| 45 | Low AI confidence causes human escalation | COMPLETE | `POST /simulation/low-confidence` sets confidence below threshold → ESCALATED; visible in escalations queue |
| 46 | Customer STOP stops communication | COMPLETE | `POST /simulation/opt-out` sets `Customer.opted_out=true`; policy engine returns STOP immediately |
| 47 | Maximum attempts stops communication | COMPLETE | `POST /simulation/max-attempts` sets contact_attempts ≥ max; policy engine returns STOP |
| 48 | 500-case evaluation executes | COMPLETE | `POST /demo/run-batch` runs EvaluationService against all DB cases; results returned |
| 49 | Evaluation metrics are displayed | COMPLETE | Results available via API; `Run recovery scan` on Command Center triggers and refreshes |
| 50 | Frontend contains no hardcoded financial state | COMPLETE | All financial metrics (amounts, rates, counts) fetched from backend; frontend renders dynamically |

---

## Non-Negotiable Architecture Checks

| Rule | Status |
|---|---|
| AI never invents financial amounts | ✅ ERV = DB amount × risk probability |
| AI never alters financial truth | ✅ AI produces recommendations only; Tool Gateway executes |
| AI never bypasses policy | ✅ PolicyEngine.evaluate() runs in Tool Gateway; AI cannot skip it |
| AI never directly calls payment APIs | ✅ Only Tool Gateway calls providers |
| MCP does not bypass Policy Engine | ✅ MCP tools route through default_gateway |
| No uncontrolled financial actions | ✅ idempotency_key prevents duplicate actions |
| No hardcoded financial metrics in frontend | ✅ All values from API |

---

## Blocking External Dependencies

The following items require external configuration that cannot be completed from the repository alone:

| # | Requirement | Blocker |
|---|---|---|
| B1 | Live Razorpay payment processing | Requires RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET from Razorpay Dashboard |
| B2 | Durable Temporal workflows in production | Requires a running Temporal cluster (Temporal Cloud or self-hosted) |
| B3 | LLM-powered AI reasoning | Requires OPENAI_API_KEY or ANTHROPIC_API_KEY |
| B4 | WhatsApp live messages | Requires WHATSAPP_PROVIDER_TOKEN from a WhatsApp Business provider |
| B5 | Email live delivery | Requires EMAIL_PROVIDER_API_KEY |
| B6 | Render production URLs | Requires actual Render deployment to determine service URLs |

All blockers have production-ready simulation fallbacks that operate identically to the live versions for demo and development purposes.
