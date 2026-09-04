"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "./app-shell";
import { api, formatInr } from "../lib/api-client";
import type { Strategy } from "../lib/api-client";

export function AnalyticsPage() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.analytics>> | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  useEffect(() => { Promise.all([api.analytics(), api.strategies()]).then(([nextData, nextStrategies]) => { setData(nextData); setStrategies(nextStrategies); }); }, []);
  return <AppShell title="Analytics"><PageHeading eyebrow="MEASURE OUTCOMES" title="Recovery analytics" subtitle="Financial truth from the RecoverX API." />{!data ? <div className="loading-state">Loading analytics...</div> : <><div className="metric-grid"><Metric label="Revenue at risk" value={formatInr(data.revenue_at_risk)} /><Metric label="Revenue targeted" value={formatInr(data.revenue_targeted)} /><Metric label="Revenue recovered" value={formatInr(data.revenue_recovered)} /><Metric label="Recovery rate" value={`${(data.recovery_rate * 100).toFixed(1)}%`} /></div><section className="panel route-panel"><div className="panel-header"><h2>Strategy performance</h2><span className="muted">Live backend aggregation</span></div>{strategies.map((item) => <div className="analytics-row" key={item.strategy}><b>{item.strategy}</b><span>{item.attempts} attempts</span><span>{item.success} recoveries</span><strong>{formatInr(item.recovered)}</strong></div>)}</section></>}</AppShell>;
}

export function EscalationsPage() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof api.cases>>["items"]>([]);
  const [notice, setNotice] = useState("");
  useEffect(() => { api.cases(500).then((result) => setItems(result.items.filter((item) => item.status === "ESCALATED"))); }, []);
  const resolve = async (caseId: string, resolution: string) => { try { await api.resolveEscalation(caseId, resolution); setItems((current) => current.filter((item) => item.id !== caseId)); setNotice(`Case ${caseId} marked ${resolution.toLowerCase()}.`); } catch { setNotice("Unable to resolve escalation. Check your role and retry."); } };
  return <AppShell title="Escalations"><PageHeading eyebrow="HUMAN REVIEW QUEUE" title="Escalations" subtitle="Cases that require an operator decision." />{notice && <output className="inline-notice">{notice}</output>}<section className="panel route-panel">{items.length ? items.map((item) => <div className="queue-row" key={item.id}><Link href={`/cases/${item.id}`}><span><b>{item.customer}</b><small>{item.id} · {item.policy_decision}</small></span></Link><strong>{formatInr(item.amount)}</strong><span className="status status-escalated">{item.status}</span><div className="queue-actions"><button className="secondary-button" onClick={() => resolve(item.id, "APPROVE")}>Approve</button><button className="secondary-button" onClick={() => resolve(item.id, "REJECT")}>Reject</button></div></div>) : <div className="empty-state"><h2>No escalations currently require attention</h2><p>You&apos;re all caught up.</p></div>}</section></AppShell>;
}

export function IntegrationsPage() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.integrationStatus>> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.integrationStatus().then(setData).catch(() => setError("Unable to load integration status."));
  }, []);

  return (
    <AppShell title="Integrations">
      <PageHeading eyebrow="PROVIDER CONNECTIONS" title="Integrations" subtitle="Real provider state reported by the RecoverX API." />
      {error && <div className="error-state" role="alert">{error}</div>}
      {!data ? <div className="loading-state">Loading integration status…</div> : (
        <>
          <div className="metric-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            <Metric label="Total integrations" value={String(data.counts.total)} />
            <Metric label="Connected" value={String(data.counts.connected)} />
            <Metric label="Simulated" value={String(data.counts.simulated)} />
            <Metric label="Not configured" value={String(data.counts.not_configured)} />
          </div>
          <section className="integration-grid">
            {data.integrations.map((item) => (
              <Integration key={item.name} name={item.name} category={item.category} status={item.status} detail={item.detail} label={item.label} />
            ))}
          </section>
        </>
      )}
    </AppShell>
  );
}

export function PoliciesPage() {
  const [policy, setPolicy] = useState<Awaited<ReturnType<typeof api.policy>> | null>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => { api.policy().then(setPolicy).catch(() => setNotice("Unable to load policy settings.")); }, []);
  const save = async () => {
    if (!policy) return;
    try { await api.updatePolicy(policy); setNotice("Policy updated successfully."); } catch { setNotice("Policy update failed."); }
  };
  return <AppShell title="Policies"><PageHeading eyebrow="GUARDRAILS" title="Policy management" subtitle="Deterministic controls for recovery actions." />{!policy ? <div className="loading-state">Loading policy settings...</div> : <section className="panel policy-form">{([['max_auto_action_amount', 'Maximum auto-action amount'], ['human_approval_above_amount', 'Human approval above amount'], ['max_contact_attempts', 'Maximum contact attempts'], ['escalate_after_days', 'Escalate after days'], ['min_ai_confidence', 'Minimum AI confidence']] as const).map(([key, label]) => <label key={key}>{label}<input type="number" step={key === "min_ai_confidence" ? "0.01" : "1"} value={policy[key]} onChange={(event) => setPolicy({ ...policy, [key]: Number(event.target.value) })} /></label>)}<label>Preferred channels<input value={policy.preferred_channels} onChange={(event) => setPolicy({ ...policy, preferred_channels: event.target.value })} /></label><label>Supported languages<input value={policy.supported_languages} onChange={(event) => setPolicy({ ...policy, supported_languages: event.target.value })} /></label><button className="primary-button" onClick={save}>Save policy</button>{notice && <div className="inline-notice">{notice}</div>}</section>}</AppShell>;
}

function PageHeading({ eyebrow, title, subtitle }: Readonly<{ eyebrow: string; title: string; subtitle: string }>) { return <div className="route-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="subheading">{subtitle}</p></div><Link className="secondary-button" href="/">Overview</Link></div>; }
function Metric({ label, value }: Readonly<{ label: string; value: string }>) { return <div className="metric-card"><span>{label}</span><b className="metric-value">{value}</b></div>; }
function Integration({ name, category, status, detail, label }: Readonly<{ name: string; category?: string; status: string; detail: string; label: string }>) {
  const statusClass = status === "CONNECTED" ? "connected" : status === "SIMULATED" ? "simulated" : "not-configured";
  return <div className="panel integration-card"><span className="integration-dot" data-status={status} /><div><b>{name}</b><small>{category ? `${category} · ` : ""}{detail}</small></div><strong className={statusClass}>{label}</strong></div>;
}
