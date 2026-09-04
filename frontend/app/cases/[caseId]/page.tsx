"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "../../../components/app-shell";
import { api, formatInr, labelForEvent } from "../../../lib/api-client";
import type { AuditEvent, Customer, RecoveryCase } from "../../../lib/api-client";

export default function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [item, setItem] = useState<RecoveryCase | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [notice, setNotice] = useState("");
  const prevStatus = useRef<string>("");

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const [nextItem, nextEvents] = await Promise.all([api.caseById(caseId), api.audit(100, caseId)]);
      setItem(nextItem);
      setEvents([...nextEvents.items].reverse());
      if (nextItem.customer_id) {
        const nextCustomer = await api.customer(nextItem.customer_id);
        setCustomer(nextCustomer);
      }
      if (prevStatus.current && prevStatus.current !== nextItem.status) {
        setNotice(`Case updated: ${nextItem.status}`);
      }
      prevStatus.current = nextItem.status;
    } catch {
      setNotice("Unable to load this recovery case.");
    }
  }, [caseId]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(initialLoad);
  }, [load]);

  // Poll every 8 s so payment simulation is reflected automatically
  useEffect(() => {
    const id = setInterval(() => { load(); }, 8000);
    return () => clearInterval(id);
  }, [load]);

  const execute = async () => {
    if (!item) return;
    setNotice("Executing policy-approved recovery…");
    try {
      const result = await api.executeCase(item.id);
      setItem({ ...item, status: result.status === "EXECUTED" ? "WAITING_FOR_PAYMENT" : result.status, action_executed: true });
      setNotice("Recovery executed successfully.");
      await load();
    } catch {
      setNotice("Recovery requires human approval or could not be executed. Check policy limits.");
    }
  };

  const stop = async () => {
    if (!item) return;
    try {
      await api.stopCase(item.id);
      setItem({ ...item, status: "STOPPED" });
      setNotice("Case stopped.");
    } catch {
      setNotice("Unable to stop this case.");
    }
  };

  const approve = async () => {
    if (!item) return;
    try {
      const result = await api.approveCase(item.id);
      setItem({ ...item, status: result.status, action_executed: true });
      setNotice("Recovery approved and dispatched.");
      await load();
    } catch {
      setNotice("Approval failed. The policy or provider rejected this action.");
    }
  };

  const isTerminal = item?.status === "RECOVERED" || item?.status === "STOPPED" || item?.status === "EXPIRED";

  return (
    <AppShell title="Case investigation">
      <Link className="back-link" href="/cases">← Back to cases</Link>
      {!item ? <div className="loading-state">Loading case investigation…</div> : (
        <>
          <div className="route-heading">
            <div>
              <p className="eyebrow">RECOVERY CASE {item.id}</p>
              <h1>{item.customer}</h1>
              <p className="subheading">{labelForEvent(item.event_type)} · {formatInr(item.amount)}</p>
            </div>
            <span className={`status status-${item.status.toLowerCase()}`}>{item.status}</span>
          </div>

          {notice && <output className="inline-notice">{notice}</output>}

          {/* Action Row */}
          <div className="action-row" style={{ marginBottom: "1.5rem" }}>
            {item.status === "ESCALATED" && (
              <button className="primary-button" onClick={approve}>Approve recovery</button>
            )}
            <button className="primary-button" onClick={execute} disabled={isTerminal || item.status === "ESCALATED" || item.status === "WAITING_FOR_PAYMENT"}>
              Execute recovery
            </button>
            <button className="secondary-button" onClick={stop} disabled={isTerminal}>
              Stop case
            </button>
          </div>

          <div className="detail-grid">
            {/* Risk & Core Metrics */}
            <section className="panel">
              <div className="panel-header"><h2>Risk assessment</h2><span className="status status-recovered">Deterministic</span></div>
              <div className="detail-metrics">
                <Metric label="Risk score" value={`${item.risk_score}/100`} />
                <Metric label="Recovery probability" value={`${Math.round(item.recovery_probability * 100)}%`} />
                <Metric label="Expected recovery" value={formatInr(item.expected_recovery_value)} />
                <Metric label="AI confidence" value={`${Math.round(item.ai_confidence * 100)}%`} />
                <Metric label="Contact attempts" value={String(item.contact_attempts)} />
                {item.failure_reason && <Metric label="Failure reason" value={item.failure_reason.replace(/_/g, " ")} />}
              </div>
            </section>

            {/* Customer Intelligence */}
            <section className="panel customer-context">
              <div className="panel-header"><h2>Customer intelligence</h2><span className="status status-recovered">Explainable</span></div>
              {customer ? (
                <>
                  <h3>{customer.name}</h3>
                  <p className="muted">{customer.email} · {customer.phone}</p>
                  <div className="context-grid">
                    <Metric label="Lifetime value" value={formatInr(customer.lifetime_value)} />
                    <Metric label="Reliability" value={`${customer.payment_reliability_pct}%`} />
                    <Metric label="Successful payments" value={String(customer.successful_payments)} />
                    <Metric label="Failed payments" value={String(customer.failed_payments)} />
                    <Metric label="Historical recovery" value={`${Math.round(customer.historical_recovery_rate * 100)}%`} />
                    <Metric label="Preferred channel" value={customer.preferred_channel} />
                    <Metric label="Preferred language" value={customer.preferred_language} />
                  </div>
                </>
              ) : <div className="loading-state">Loading customer context…</div>}
            </section>

            {/* AI Diagnosis */}
            <section className="panel">
              <div className="panel-header"><h2>AI diagnosis</h2><span className="status status-actionable">LangGraph</span></div>
              <div className="ai-block">
                <p className="eyebrow">DIAGNOSIS</p>
                <h3>{item.diagnosis ?? "Payment issue diagnosed"}</h3>
                {item.root_cause && <p><strong>Root cause:</strong> {item.root_cause.replace(/_/g, " ")}</p>}
                {item.ai_reasoning && <p className="muted" style={{ marginTop: "0.5rem" }}>{item.ai_reasoning}</p>}
              </div>
              <div style={{ marginTop: "1rem" }}>
                <p><strong>Recommended strategy:</strong> {labelForEvent(item.recommended_action)}</p>
              </div>
            </section>

            {/* Policy Evaluation */}
            <section className="panel">
              <div className="panel-header"><h2>Policy evaluation</h2><span className="status status-recovered">Backend guardrail</span></div>
              <ul className="check-list">
                <li>Amount evaluated against merchant auto-action limit</li>
                <li>AI confidence checked against policy threshold</li>
                <li>Contact attempts tracked and enforced</li>
                <li>Opt-out status checked before any action</li>
              </ul>
              <h3 className="policy-decision">{item.policy_decision}</h3>
            </section>

            {/* Payment Link */}
            {item.payment_link && (
              <section className="panel">
                <div className="panel-header"><h2>Payment link</h2><span className={`status status-${item.payment_link.status.toLowerCase()}`}>{item.payment_link.status}</span></div>
                <div className="context-grid">
                  <Metric label="Amount" value={formatInr(item.payment_link.amount)} />
                  <Metric label="Status" value={item.payment_link.status} />
                  {(item.payment_link.payment_url || item.payment_link.short_url) && (
                    <div className="detail-metric">
                      <span>Payment URL</span>
                      <b><a href={item.payment_link.payment_url || item.payment_link.short_url} target="_blank" rel="noopener noreferrer">{item.payment_link.payment_url || item.payment_link.short_url}</a></b>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Escalation */}
            {item.escalation && (
              <section className="panel">
                <div className="panel-header"><h2>Escalation</h2><span className="status status-escalated">Human review</span></div>
                <p><strong>Reason:</strong> {item.escalation.reason.replace(/,/g, ", ")}</p>
                {item.escalation.resolution && <p><strong>Resolution:</strong> {item.escalation.resolution}</p>}
                {item.escalation.resolution_notes && <p className="muted">{item.escalation.resolution_notes}</p>}
              </section>
            )}

            {/* Communications */}
            {item.communications && item.communications.length > 0 && (
              <section className="panel">
                <div className="panel-header"><h2>Communications</h2><span className="muted">{item.communications.length} message{item.communications.length !== 1 ? "s" : ""}</span></div>
                <div className="activity-list">
                  {item.communications.map((msg) => (
                    <div key={msg.id} className="activity-item">
                      <span className="activity-icon blue">
                        {msg.channel === "whatsapp" ? "📱" : "📧"}
                      </span>
                      <span className="activity-copy">
                        <b>{msg.channel.toUpperCase()} {msg.direction}</b>
                        <small>{msg.content.slice(0, 120)}{msg.content.length > 120 ? "…" : ""}</small>
                      </span>
                      <span className="activity-time">{new Date(msg.created_at).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Promises to Pay */}
            {item.promises_to_pay && item.promises_to_pay.length > 0 && (
              <section className="panel">
                <div className="panel-header"><h2>Promise to Pay</h2><span className="muted">{item.promises_to_pay.length} promise{item.promises_to_pay.length !== 1 ? "s" : ""}</span></div>
                {item.promises_to_pay.map((p) => (
                  <div key={p.id} className="queue-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
                    <span><b>{formatInr(p.amount)}</b> by {new Date(p.promised_date).toLocaleDateString()}</span>
                    <span className={`status status-${p.status.toLowerCase()}`}>{p.status}</span>
                    {p.fulfilled && <span className="status status-recovered">Fulfilled</span>}
                  </div>
                ))}
              </section>
            )}

            {/* Timeline */}
            <section className="panel" style={{ gridColumn: "1 / -1" }}>
              <div className="panel-header"><h2>Complete timeline</h2><span className="muted">{events.length} events</span></div>
              <div className="timeline">
                {events.length ? events.map((event) => (
                  <Timeline
                    key={`${event.event_name}-${event.created_at}`}
                    label={event.event_name}
                    time={new Date(event.created_at).toLocaleString()}
                    payload={event.payload}
                  />
                )) : <p className="muted">No audit events recorded for this case.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </AppShell>
  );
}

function Metric({ label, value }: Readonly<{ label: string; value: string }>) {
  return <div className="detail-metric"><span>{label}</span><b>{value}</b></div>;
}

function Timeline({ label, time, payload }: Readonly<{ label: string; time: string; payload?: Record<string, unknown> }>) {
  return (
    <div className="timeline-item">
      <span className="timeline-dot" />
      <span>
        <b>{label}</b>
        {payload && Object.keys(payload).length > 0 && (
          <small style={{ display: "block" }}>
            {Object.entries(payload).slice(0, 3).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(" · ")}
          </small>
        )}
        <small>{time}</small>
      </span>
    </div>
  );
}
