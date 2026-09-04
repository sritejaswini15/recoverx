"use client";

import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { AppShell } from "../../components/app-shell";
import { api, formatInr } from "../../lib/api-client";
import type { Analytics, Strategy } from "../../lib/api-client";

function numericValue(value: unknown): number {
  const candidate = Array.isArray(value) ? value[0] : value;
  return typeof candidate === "number" || typeof candidate === "string" ? Number(candidate) || 0 : 0;
}

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.analytics(), api.strategies()])
      .then(([a, s]) => { setData(a); setStrategies(s); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <AppShell title="Analytics">
        <div className="loading-state">Loading analytics from database…</div>
      </AppShell>
    );
  }
  if (!data) {
    return (
      <AppShell title="Analytics">
        <div className="error-state">Could not load analytics. Make sure the backend is running.</div>
      </AppShell>
    );
  }

  const strategyBarData = strategies.map((s) => ({
    name: s.strategy.replace(/_/g, " "),
    attempts: s.attempts,
    recovered: Math.round(s.recovered / 100),
    success: s.success,
  }));

  const funnelData = [
    { name: "Detected", value: data.cases, fill: "#20344f" },
    { name: "Targeted", value: Math.round(data.revenue_targeted / 100), fill: "#638bc0" },
    { name: "Recovered", value: Math.round(data.revenue_recovered / 100), fill: "#1d9b87" },
  ];

  const recoveryRatePct = (data.recovery_rate * 100).toFixed(1);
  const escalations = data.escalations ?? 0;
  const averageAiConfidence = data.average_ai_confidence ?? 0;
  const escalationRatePct = data.cases > 0 ? ((escalations / data.cases) * 100).toFixed(1) : "0.0";
  const avgTimeHours = typeof data.average_recovery_time_hours === "number"
    ? `${data.average_recovery_time_hours.toFixed(1)}h`
    : "—";

  return (
    <AppShell title="Analytics">
      <div className="route-heading">
        <div>
          <p className="eyebrow">MEASURE OUTCOMES</p>
          <h1>Recovery analytics</h1>
          <p className="subheading">All figures computed from the PostgreSQL database in real time.</p>
        </div>
      </div>

      {/* KPI Metrics */}
      <div className="metric-grid" style={{ marginBottom: "20px" }}>
        <KPICard label="Revenue at Risk" value={formatInr(data.revenue_at_risk)} sub={`${data.cases} cases detected`} color="coral" />
        <KPICard label="Revenue Targeted" value={formatInr(data.revenue_targeted)} sub="Sent for recovery" color="blue" />
        <KPICard label="Revenue Recovered" value={formatInr(data.revenue_recovered)} sub={`${recoveryRatePct}% recovery rate`} color="mint" />
        <KPICard label="Successful Recoveries" value={String(data.successful_recoveries)} sub={`${escalationRatePct}% escalation rate`} color="amber" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr .8fr", gap: "17px", marginBottom: "17px" }}>
        {/* Strategy Performance — Bar Chart */}
        <section className="panel">
          <div className="panel-header">
            <h2>Strategy performance</h2>
            <span className="muted">Recovery attempts vs. successes</span>
          </div>
          {strategyBarData.length > 0 ? (
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={strategyBarData} margin={{ top: 4, right: 10, left: -20, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#edf0f3" />
                  <XAxis dataKey="name" tick={{ fontSize: 9 }} angle={-35} textAnchor="end" interval={0} />
                  <YAxis tick={{ fontSize: 9 }} />
                  <Tooltip
                    formatter={(value: unknown, name: unknown) => {
                      const numeric = numericValue(value);
                      const key = String(name);
                      return [
                        key === "recovered" ? formatInr(numeric * 100) : numeric,
                        key === "recovered" ? "Recovered" : key === "success" ? "Successes" : "Attempts",
                      ];
                    }}
                  />
                  <Bar dataKey="attempts" fill="#e5e9ee" radius={[3, 3, 0, 0]} name="attempts" />
                  <Bar dataKey="success" fill="#1d9b87" radius={[3, 3, 0, 0]} name="success" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="muted" style={{ fontSize: 12 }}>No strategy data yet. Trigger a simulation to generate cases.</p>
          )}
        </section>

        {/* Recovery Funnel — Horizontal bars */}
        <section className="panel">
          <div className="panel-header">
            <h2>Recovery funnel</h2>
            <span className="muted">Top of funnel → recovered</span>
          </div>
          <div className="funnel" style={{ marginTop: "8px" }}>
            {funnelData.map((step, i) => {
              const max = funnelData[0].value || 1;
              const pct = ((step.value / max) * 100).toFixed(0);
              return (
                <div key={step.name}>
                  <div className="funnel-label">
                    <span>{step.name}</span>
                    <b>{i > 0 ? formatInr(step.value * 100) : step.value.toLocaleString()}</b>
                  </div>
                  <div className="funnel-track">
                    <div className="funnel-bar" style={{ width: `${pct}%`, background: step.fill }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="funnel-footer">
            <span>Recovery rate<b className="success-text"> {recoveryRatePct}%</b></span>
            <span>Avg time <b>{avgTimeHours}</b></span>
          </div>
        </section>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "17px", marginBottom: "17px" }}>
        {/* Strategy Revenue Chart */}
        <section className="panel">
          <div className="panel-header">
            <h2>Revenue recovered by strategy</h2>
            <span className="muted">₹ recovered</span>
          </div>
          {strategyBarData.length > 0 ? (
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={strategyBarData} layout="vertical" margin={{ top: 0, right: 20, left: 60, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#edf0f3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 9 }} tickFormatter={(v: number | string) => `₹${(Number(v) / 1000).toFixed(0)}k`} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={60} />
                  <Tooltip formatter={(value: unknown) => formatInr(numericValue(value) * 100)} />
                  <Bar dataKey="recovered" fill="#ef725d" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="muted" style={{ fontSize: 12 }}>No data yet.</p>
          )}
        </section>

        {/* Key Metrics Panel */}
        <section className="panel">
          <div className="panel-header"><h2>System health metrics</h2><span className="muted">From database</span></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "8px" }}>
            <StatBox label="Cases processed" value={String(data.cases)} />
            <StatBox label="Auto-approved" value={String(data.successful_recoveries)} color="teal" />
            <StatBox label="Escalations" value={String(escalations)} color="amber" />
            <StatBox label="Avg recovery time" value={avgTimeHours} color="blue" />
            <StatBox label="AI confidence avg" value={`${(averageAiConfidence * 100).toFixed(0)}%`} />
            <StatBox label="Policy violations" value={String(data.policy_violations ?? 0)} color="coral" />
            <StatBox label="Action failures" value={String(data.action_failures ?? 0)} color="coral" />
            <StatBox label="False escalations" value={String(data.false_escalations ?? 0)} />
          </div>
        </section>
      </div>

      {/* Strategy Table */}
      {strategies.length > 0 && (
        <section className="panel">
          <div className="panel-header"><h2>Strategy details</h2><span className="muted">All figures from PostgreSQL</span></div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--line)", color: "var(--muted)", fontSize: 10, textAlign: "left" }}>
                  <th style={{ padding: "10px 16px" }}>Strategy</th>
                  <th style={{ padding: "10px 16px" }}>Attempts</th>
                  <th style={{ padding: "10px 16px" }}>Successes</th>
                  <th style={{ padding: "10px 16px" }}>Recovery Rate</th>
                  <th style={{ padding: "10px 16px" }}>Revenue Recovered</th>
                  <th style={{ padding: "10px 16px" }}>Avg Time</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((s) => (
                  <tr key={s.strategy} style={{ borderBottom: "1px solid #f0f3f5" }}>
                    <td style={{ padding: "12px 16px", fontWeight: 600 }}>{s.strategy.replace(/_/g, " ")}</td>
                    <td style={{ padding: "12px 16px" }}>{s.attempts}</td>
                    <td style={{ padding: "12px 16px", color: "#1d9b87" }}>{s.success}</td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ color: "#1d9b87", fontWeight: 600 }}>
                        {s.attempts > 0 ? `${((s.success / s.attempts) * 100).toFixed(0)}%` : "—"}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px", fontFamily: "IBM Plex Mono" }}>{formatInr(s.recovered)}</td>
                    <td style={{ padding: "12px 16px", color: "var(--muted)" }}>
                      {typeof s.average_recovery_time === "number" ? `${s.average_recovery_time.toFixed(1)}h` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </AppShell>
  );
}

function KPICard({ label, value, sub, color = "" }: Readonly<{ label: string; value: string; sub: string; color?: string }>) {
  return (
    <div className={`metric-card ${color}`}>
      <div className="metric-top"><span>{label}</span></div>
      <b className="metric-value">{value}</b>
      <span className="metric-detail">{sub}</span>
      <div className="metric-spark"><span /><span /><span /><span /><span /></div>
    </div>
  );
}

function StatBox({ label, value, color = "" }: Readonly<{ label: string; value: string; color?: string }>) {
  const colorMap: Record<string, string> = { teal: "#1d9b87", amber: "#dfa840", blue: "#638bc0", coral: "#ef725d" };
  return (
    <div style={{ background: "#fafbfc", borderRadius: 7, padding: "14px", border: "1px solid var(--line)" }}>
      <div style={{ color: "var(--muted)", fontSize: 10, marginBottom: 8 }}>{label}</div>
      <div style={{ font: "600 22px 'Space Grotesk'", color: colorMap[color] ?? "var(--ink)" }}>{value}</div>
    </div>
  );
}
