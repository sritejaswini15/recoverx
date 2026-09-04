"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, formatInr, initials, labelForEvent } from "../lib/api-client";
import type { Analytics, AuditEvent, RecoveryCase, Strategy } from "../lib/api-client";

const navItems = ["Command center", "Cases", "Analytics", "Escalations", "Policies", "Integrations"];

export default function Home() {
  const router = useRouter();
  const [activeNav, setActiveNav] = useState("Command center");
  const [showAll, setShowAll] = useState(false);
  const [notice, setNotice] = useState("");
  const [period, setPeriod] = useState("Last 30 days");
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [activity, setActivity] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [isAuthenticated] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return Boolean(window.localStorage.getItem("recoverx_access_token"));
  });
  const visibleCases = showAll ? cases : cases.slice(0, 3);
  const escalationCount = cases.filter((c) => c.status === "ESCALATED").length;

  useEffect(() => {
    if (!window.localStorage.getItem("recoverx_access_token")) {
      router.replace("/login");
      return;
    }
    Promise.all([api.analytics(), api.cases(), api.strategies(), api.audit()])
      .then(([nextAnalytics, nextCases, nextStrategies, nextActivity]) => {
        setAnalytics(nextAnalytics);
        setCases(nextCases.items);
        setStrategies(nextStrategies);
        setActivity([...nextActivity.items].reverse());
      })
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  }, [router]);

  const notify = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2800);
  };

  const runScan = async () => {
    setNotice("Running 500-case recovery simulation...");
    try {
      await api.runBatch();
      // Refresh all data from real endpoints after batch completes
      const [nextAnalytics, nextCases, nextStrategies, nextActivity] = await Promise.all([
        api.analytics(), api.cases(), api.strategies(), api.audit(),
      ]);
      setAnalytics(nextAnalytics);
      setCases(nextCases.items);
      setStrategies(nextStrategies);
      setActivity([...nextActivity.items].reverse());
      setNotice("Recovery scan complete");
    } catch { setNotice("Recovery scan failed. Check the API and retry."); }
  };

  if (isAuthenticated === null || !isAuthenticated) {
    return (
      <main className="login-page">
        <div className="loading-state" style={{ minWidth: 280, textAlign: "center" }}>
          Authenticating RecoverX control plane...
        </div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">R</span><span>recover<span className="brand-x">X</span></span></div>
        <div className="workspace-switcher"><span className="workspace-avatar">AC</span><span><b>Acme Commerce</b><small>Production workspace</small></span><span className="chevron">⌄</span></div>
        <nav className="nav-list" aria-label="Main navigation">
          {navItems.map((item, index) => <Link key={item} href={item === "Command center" ? "/" : `/${item.toLowerCase()}`} className={`nav-item ${activeNav === item ? "active" : ""}`} onClick={() => setActiveNav(item)}><span className="nav-icon">{["⌁", "◫", "◒", "!", "⌘", "◈"][index]}</span>{item}{item === "Escalations" && escalationCount > 0 && <span className="nav-badge">{escalationCount}</span>}</Link>)}
        </nav>
        <UserChip />
      </aside>

      <section className="content">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-mark">R</span> recover<span className="brand-x">X</span></div>
          <div className="breadcrumb">Revenue operations <span>/</span> {activeNav}</div>
          <div className="top-actions">
            <button onClick={() => api.logout()} className="text-button" style={{ fontSize: "12px", color: "#647287" }}>
              Sign out
            </button>
            <div className="top-avatar">RX</div>
          </div>
        </header>
        <div className="page-wrap">
          <div className="page-heading"><div><p className="eyebrow">LIVE RECOVERX CONTROL PLANE · {analytics?.mode.toUpperCase() ?? "CONNECTING"} MODE</p><h1>{activeNav === "Command center" ? "Good morning, Ananya" : activeNav}</h1><p className="subheading">Here&apos;s what&apos;s happening with your revenue recovery today.</p></div><div className="heading-actions"><select value={period} onChange={(event) => setPeriod(event.target.value)} aria-label="Time period"><option>Last 30 days</option><option>Last 7 days</option><option>Last 90 days</option></select><button className="primary-button" onClick={runScan} disabled={loading}>＋ Run recovery scan</button></div></div>

          {activeNav === "Command center" ? <>
            {loadError && <div className="error-state" role="alert">Unable to load recovery data. Start the API on port 8000 and refresh.</div>}
            {loading && <div className="loading-state">Loading live recovery signals...</div>}
            {analytics && <>
            <section className="metric-grid">
              <Metric label="Revenue at risk" value={formatInr(analytics.revenue_at_risk)} change="live" direction="up" tone="coral" detail={`across ${analytics.cases.toLocaleString()} active cases`} />
              <Metric label="Revenue recovered" value={formatInr(analytics.revenue_recovered)} change="live" direction="up" tone="mint" detail={`${analytics.successful_recoveries.toLocaleString()} successful recoveries`} />
              <Metric label="Recovery rate" value={`${(analytics.recovery_rate * 100).toFixed(1)}%`} change="live" direction="up" tone="amber" detail="from deterministic demo engine" />
              <Metric label="Needs attention" value={String(cases.filter((item) => item.status === "ESCALATED").length)} change="live" direction="flat" tone="blue" detail="in human review queue" />
            </section>
            <section className="main-grid"><div className="panel funnel-panel"><PanelHeader title="Recovery funnel" action="View analytics" onAction={() => setActiveNav("Analytics")} /><div className="funnel"><FunnelRow label="Revenue risk cases" value={String(analytics.funnel.risk_cases)} width="100%" color="navy" /><FunnelRow label="Eligible for recovery" value={String(analytics.funnel.eligible)} width={`${analytics.funnel.eligible / Math.max(analytics.funnel.risk_cases, 1) * 100}%`} color="blue" /><FunnelRow label="Recovery actions" value={String(analytics.funnel.actions)} width={`${analytics.funnel.actions / Math.max(analytics.funnel.risk_cases, 1) * 100}%`} color="teal" /><FunnelRow label="Successful recoveries" value={String(analytics.funnel.successful)} width={`${analytics.funnel.successful / Math.max(analytics.funnel.risk_cases, 1) * 100}%`} color="green" /></div><div className="funnel-footer"><span><b>{formatInr(analytics.revenue_targeted)}</b> targeted</span><span><b>{formatInr(analytics.revenue_recovered)}</b> recovered</span><span className="success-text">{(analytics.recovery_rate * 100).toFixed(1)}% recovery rate</span></div></div><div className="panel activity-panel"><PanelHeader title="Recovery pulse" action="Live" /><div className="pulse-header"><div><b>{formatInr(analytics.revenue_recovered)}</b><span>recovered this period</span></div><div className="pulse-pill">Backend analytics</div></div><div className="chart empty-chart">Historical trend data is not available from the API yet.</div></div></section>
            <section className="lower-grid"><div className="panel cases-panel"><PanelHeader title="Priority recovery cases" action="View all cases →" onAction={() => setActiveNav("Cases")} /><div className="case-table"><div className="table-row table-head"><span>Customer</span><span>Amount at risk</span><span>Expected recovery</span><span>Risk</span><span>Status</span></div>{visibleCases.map((item) => <Link className="table-row case-row" href={`/cases/${item.id}`} key={item.id}><span className="customer-cell"><span className={`customer-avatar avatar-${initials(item.customer)}`}>{initials(item.customer)}</span><span><b>{item.customer}</b><small>{labelForEvent(item.event_type)} · {item.id}</small></span></span><span className="amount-cell">{formatInr(item.amount)}</span><span>{formatInr(item.expected_recovery_value)}<small className="muted">{Math.round(item.recovery_probability * 100)}% probability</small></span><span><span className={`risk ${item.risk_score > 75 ? "high" : "medium"}`}>{item.risk_score}</span></span><span><span className={`status status-${item.status.toLowerCase()}`}>{item.status}</span></span></Link>)}</div><button className="text-button" onClick={() => setShowAll(!showAll)}>{showAll ? "Show less" : "View all priority cases"} <span>→</span></button></div><div className="panel strategy-panel"><PanelHeader title="Strategy performance" action="Details" onAction={() => setActiveNav("Analytics")} /><div className="strategy-list">{strategies.map((item) => <Strategy key={item.strategy} name={labelForEvent(item.strategy)} icon="↗" attempts={`${item.attempts} attempts`} success={String(item.success)} amount={formatInr(item.recovered)} width={`${item.attempts ? item.success / item.attempts * 100 : 0}%`} color="teal" />)}</div></div></section>
            <section className="panel activity-feed"><PanelHeader title="Recent activity" action="Live audit" onAction={() => notify("Showing the latest audit events")}/><div className="activity-list">{activity.length ? activity.map((item) => <Activity key={`${item.event_name}-${item.created_at}`} icon="•" title={labelForEvent(item.event_name)} detail={item.case_id ?? "System event"} time={new Date(item.created_at).toLocaleString()} color="blue" />) : <div className="empty-state">No recovery activity yet.</div>}</div></section>
            </>}
          </> : <EmptyState section={activeNav} onAction={() => setActiveNav("Command center")} />}
        </div>
      </section>
      {notice && <div className="toast">✓ {notice}</div>}
    </main>
  );
}

function Metric({ label, value, change, direction, tone, detail }: Readonly<{ label: string; value: string; change: string; direction: string; tone: string; detail: string }>) { return <div className={`metric-card ${tone}`}><div className="metric-top"><span>{label}</span><span className={`metric-change ${direction}`}>{direction === "up" ? "↑" : "•"} {change}</span></div><b className="metric-value">{value}</b><span className="metric-detail">{detail}</span><div className="metric-spark"><span /><span /><span /><span /><span /></div></div>; }
function PanelHeader({ title, action, onAction }: Readonly<{ title: string; action: string; onAction?: () => void }>) { return <div className="panel-header"><h2>{title}</h2><button onClick={onAction}>{action}</button></div>; }
function FunnelRow({ label, value, width, color }: Readonly<{ label: string; value: string; width: string; color: string }>) { return <div className="funnel-row"><div className="funnel-label"><span>{label}</span><b>{value}</b></div><div className="funnel-track"><div className={`funnel-bar ${color}`} style={{ width }} /></div></div>; }
function Strategy({ name, icon, attempts, success, amount, width, color }: Readonly<{ name: string; icon: string; attempts: string; success: string; amount: string; width: string; color: string }>) { return <div className="strategy"><div className="strategy-title"><span className={`strategy-icon ${color}`}>{icon}</span><span><b>{name}</b><small>{attempts}</small></span><strong>{amount}</strong></div><div className="strategy-bar"><div className={`strategy-progress ${color}`} style={{ width }} /></div><div className="strategy-meta"><span><b>{success}</b> successful</span><span>{width.replace("%", "")}% conversion</span></div></div>; }
function Activity({ icon, title, detail, time, color, amount }: Readonly<{ icon: string; title: string; detail: string; time: string; color: string; amount?: string }>) { return <div className="activity-item"><span className={`activity-icon ${color}`}>{icon}</span><span className="activity-copy"><b>{title}</b><small>{detail}</small></span>{amount && <strong className="activity-amount">{amount}</strong>}<span className="activity-time">{time}</span></div>; }
function EmptyState({ section, onAction }: Readonly<{ section: string; onAction: () => void }>) { return <div className="empty-state"><span className="empty-icon">◈</span><h2>{section} is ready</h2><p>This workspace is wired for the {section.toLowerCase()} workflow. Explore the command center for live recovery signals.</p><button className="primary-button" onClick={onAction}>Back to command center</button></div>; }

function UserChip() {
  const [user] = useState<{ name: string; role: string } | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem("recoverx_user");
      return raw ? JSON.parse(raw) as { name: string; role: string } : null;
    } catch {
      return null;
    }
  });
  const name = user?.name ?? "RecoverX User";
  const role = user?.role ?? "Operator";
  const av = name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="sidebar-bottom">
      <div className="user-chip">
        <span className="user-avatar">{av}</span>
        <span><b>{name}</b><small>{role}</small></span>
        <button
          onClick={() => api.logout()}
          style={{ marginLeft: "auto", background: "none", border: 0, color: "#ef725d", fontSize: "11px", fontWeight: 600 }}
          title="Sign out"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
