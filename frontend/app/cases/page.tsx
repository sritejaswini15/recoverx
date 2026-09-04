"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "../../components/app-shell";
import { api, formatInr, initials, labelForEvent, RecoveryCase } from "../../lib/api-client";

export default function CasesPage() {
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [status, setStatus] = useState("ALL");
  const [query, setQuery] = useState("");
  const [error, setError] = useState(false);
  useEffect(() => { api.cases(500).then((result) => setCases(result.items)).catch(() => setError(true)); }, []);
  const visible = useMemo(() => cases.filter((item) => (status === "ALL" || item.status === status) && item.customer.toLowerCase().includes(query.toLowerCase())).sort((a, b) => b.expected_recovery_value - a.expected_recovery_value), [cases, query, status]);
  return <AppShell title="Cases"><div className="route-heading"><div><p className="eyebrow">RECOVERY OPERATIONS</p><h1>Case queue</h1><p className="subheading">Prioritized by expected recovery value.</p></div><Link className="primary-button" href="/">Command center</Link></div>
    {error && <div className="error-state" role="alert">Unable to load recovery cases. Check the API and retry.</div>}
    <section className="panel route-panel"><div className="filter-bar"><input aria-label="Search customers" placeholder="Search customers" value={query} onChange={(event) => setQuery(event.target.value)} /><select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="ALL">All statuses</option><option>NEW</option><option>ACTIONABLE</option><option>WAITING_FOR_PAYMENT</option><option>ESCALATED</option><option>RECOVERED</option><option>STOPPED</option><option>EXPIRED</option></select><span className="result-count">{visible.length} cases</span></div><div className="case-table wide-table"><div className="table-row table-head"><span>Customer</span><span>Revenue type</span><span>Amount</span><span>Risk</span><span>Expected recovery</span><span>Status</span></div>{visible.map((item) => <Link className="table-row case-row" href={`/cases/${item.id}`} key={item.id}><span className="customer-cell"><span className="customer-avatar">{initials(item.customer)}</span><span><b>{item.customer}</b><small>{item.id}</small></span></span><span>{labelForEvent(item.event_type)}</span><span className="amount-cell">{formatInr(item.amount)}</span><span><span className={`risk ${item.risk_score > 75 ? "high" : "medium"}`}>{item.risk_score}</span></span><span>{formatInr(item.expected_recovery_value)}<small className="muted">{Math.round(item.recovery_probability * 100)}% probability</small></span><span><span className={`status status-${item.status.toLowerCase()}`}>{item.status}</span></span></Link>)}</div>{visible.length === 0 && <div className="empty-state"><h2>No recovery cases found</h2><p>Try changing your filters.</p></div>}</section>
  </AppShell>;
}
