"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "../../components/app-shell";
import { api, formatInr } from "../../lib/api-client";
import type { RecoveryCase } from "../../lib/api-client";

const EVENT_TYPES = [
  { value: "PAYMENT_FAILURE", label: "Payment failure" },
  { value: "SUBSCRIPTION_HALTED", label: "Subscription halted" },
  { value: "INVOICE_OVERDUE", label: "Invoice overdue" },
  { value: "CHECKOUT_ABANDONED", label: "Checkout abandoned" },
  { value: "PAYMENT_LINK_ABANDONED", label: "Payment Link abandoned" },
];

export default function SimulatorPage() {
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [selected, setSelected] = useState<RecoveryCase | null>(null);
  const [notice, setNotice] = useState("");
  const [eventType, setEventType] = useState("PAYMENT_FAILURE");
  const [promiseDate, setPromiseDate] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });
  const [loading, setLoading] = useState<string | null>(null);

  useEffect(() => {
    api.cases(100).then((result) => {
      setCases(result.items);
      setSelected(result.items[0] ?? null);
    }).catch(() => setNotice("Unable to load simulator cases."));
  }, []);

  const withNotice = async (label: string, fn: () => Promise<string>) => {
    setLoading(label);
    setNotice(`Running: ${label}…`);
    try {
      const msg = await fn();
      setNotice(msg);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setNotice(`Failed: ${label}. ${message}`);
    } finally {
      setLoading(null);
      // Refresh selected case
      if (selected) {
        api.caseById(selected.id).then((refreshed) => setSelected(refreshed)).catch(() => null);
      }
    }
  };

  const triggerEvent = () => withNotice("Trigger event", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulateEvent(eventType, selected.customer_id, selected.amount);
    return result.case_id ? `Event processed → Case ${result.case_id} (${result.status})` : "Event processed. No recovery case created.";
  });

  const simulatePay = () => withNotice("Pay now", async () => {
    if (!selected) throw new Error("No case selected");
    const next = await api.simulatePayment(selected.id);
    setSelected({ ...selected, status: next.status, recovered_amount: next.recovered_amount });
    return `Payment captured. Case status: ${next.status}. Recovered: ${formatInr(next.recovered_amount)}.`;
  });

  const simulateTimeout = () => withNotice("Provider timeout", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulateTimeout(selected.id);
    return `Timeout simulated. Case status: ${result.status}. Retry recorded safely.`;
  });

  const simulateOptOut = () => withNotice("Customer opt-out", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulateOptOut(selected.customer_id);
    return `Customer opted out: ${result.opted_out}. Future recovery communications are stopped.`;
  });

  const simulateLowConfidence = () => withNotice("Low AI confidence", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulateLowConfidence(selected.id);
    return `Low-confidence decision escalated: ${result.status}.`;
  });

  const simulateMaxAttempts = () => withNotice("Maximum attempts", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulateMaxAttempts(selected.id);
    return `Maximum attempts enforced: ${result.status}.`;
  });

  const simulateInvalidAi = () => withNotice("Invalid AI response", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulateInvalidAi(selected.id);
    return `Invalid AI output safely routed to human review: ${result.status}.`;
  });

  const createPromise = () => withNotice("Promise to Pay", async () => {
    if (!selected) throw new Error("No case selected");
    const result = await api.simulatePromise(selected.id, selected.amount, `${promiseDate}T00:00:00Z`);
    return `Promise to Pay created: ${result.promise_id}. Temporal will monitor for fulfillment.`;
  });

  return (
    <AppShell title="Simulator">
      <div className="route-heading">
        <div>
          <p className="eyebrow">DEVELOPER DEMO ENVIRONMENT</p>
          <h1>RecoverX Simulation Center</h1>
          <p className="subheading">Exercise real backend state transitions through the simulated Razorpay provider.</p>
        </div>
        <Link className="secondary-button" href={selected ? `/cases/${selected.id}` : "/cases"}>Open case</Link>
      </div>

      <div className="detail-grid">
        {/* Case Selector */}
        <section className="panel simulator-list">
          <div className="panel-header"><h2>Select recovery case</h2><span className="muted">{cases.length} loaded</span></div>
          {cases.slice(0, 15).map((item) => (
            <button
              className={`sim-case ${selected?.id === item.id ? "selected" : ""}`}
              key={item.id}
              onClick={() => setSelected(item)}
            >
              <span>
                <b>{item.customer}</b>
                <small>{item.id} · {item.status}</small>
              </span>
              <strong>{formatInr(item.amount)}</strong>
            </button>
          ))}
        </section>

        {/* Simulation Controls */}
        <section className="panel simulator-panel">
          {selected ? (
            <>
              <p className="eyebrow">RECOVERX FAILURE LAB</p>
              <h2>{selected.customer}</h2>
              <p className="subheading">{formatInr(selected.amount)} · {selected.id}</p>

              <div className="sim-status">
                <span>Status</span>
                <b className={`status status-${selected.status.toLowerCase()}`}>{selected.status}</b>
              </div>
              {selected.recovered_amount > 0 && (
                <div className="sim-status">
                  <span>Recovered</span>
                  <b>{formatInr(selected.recovered_amount)}</b>
                </div>
              )}

              {/* Revenue Scenario Trigger */}
              <section className="sim-section">
                <h3>Revenue scenarios</h3>
                <label>
                  Event type
                  <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
                    {EVENT_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </label>
                <button className="primary-button" onClick={triggerEvent} disabled={loading !== null}>
                  {loading === "Trigger event" ? "Processing…" : "Trigger event"}
                </button>
              </section>

              {/* Customer Payment */}
              <section className="sim-section">
                <h3>Customer payment simulation</h3>
                <p className="muted">Simulates customer clicking Pay Now → payment.captured webhook → RECOVERED</p>
                <button className="secondary-button" onClick={simulatePay} disabled={loading !== null || selected.status === "RECOVERED"}>
                  {loading === "Pay now" ? "Processing…" : "Pay now"}
                </button>
              </section>

              {/* System Failures */}
              <section className="sim-section">
                <h3>System failures</h3>
                <p className="muted">Provider timeout → safe retry logged, no duplicate action</p>
                <button className="secondary-button" onClick={simulateTimeout} disabled={loading !== null}>
                  {loading === "Provider timeout" ? "Processing…" : "Simulate provider timeout"}
                </button>
                <button className="secondary-button" onClick={simulateInvalidAi} disabled={loading !== null}>
                  {loading === "Invalid AI response" ? "Processing…" : "Simulate invalid AI response"}
                </button>
              </section>

              {/* Customer Behavior */}
              <section className="sim-section">
                <h3>Customer behavior</h3>
                <p className="muted">Opt-out → STOP rule enforced on all future contact attempts</p>
                <button className="secondary-button" onClick={simulateOptOut} disabled={loading !== null}>
                  {loading === "Customer opt-out" ? "Processing…" : "Customer opts out"}
                </button>
                <button className="secondary-button" onClick={simulateLowConfidence} disabled={loading !== null}>
                  {loading === "Low AI confidence" ? "Processing…" : "Simulate low AI confidence"}
                </button>
                <button className="secondary-button" onClick={simulateMaxAttempts} disabled={loading !== null}>
                  {loading === "Maximum attempts" ? "Processing…" : "Simulate maximum attempts"}
                </button>

                <label style={{ marginTop: "1rem", display: "block" }}>
                  Promise date
                  <input type="date" value={promiseDate} onChange={(e) => setPromiseDate(e.target.value)} />
                </label>
                <button className="secondary-button" onClick={createPromise} disabled={loading !== null}>
                  {loading === "Promise to Pay" ? "Processing…" : "Create Promise to Pay"}
                </button>
              </section>

              {notice && <div className="inline-notice" role="log" aria-live="polite">{notice}</div>}
            </>
          ) : (
            <div className="empty-state"><h2>No cases available</h2><p>Seed the database first.</p></div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
