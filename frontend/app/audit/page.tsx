"use client";

import { useEffect, useState } from "react";
import { AppShell } from "../../components/app-shell";
import { api, labelForEvent } from "../../lib/api-client";
import type { AuditEvent } from "../../lib/api-client";

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.audit(200).then((result) => setEvents(result.items)).catch(() => setError("Unable to load audit history."));
  }, []);

  return <AppShell title="Audit trail"><div className="route-heading"><div><p className="eyebrow">CONSEQUENTIAL ACTIVITY</p><h1>Audit trail</h1><p className="subheading">Immutable operational history from the RecoverX API.</p></div></div>{error && <div className="error-state" role="alert">{error}</div>}<section className="panel route-panel"><div className="panel-header"><h2>Recent events</h2><span className="muted">{events.length} events</span></div>{events.length ? <div className="activity-list">{events.map((event) => <div className="activity-item" key={`${event.event_name}-${event.created_at}`}><span className="activity-icon blue">•</span><span className="activity-copy"><b>{labelForEvent(event.event_name)}</b><small>{event.case_id ?? "System event"}</small></span><span className="activity-time">{new Date(event.created_at).toLocaleString()}</span></div>)}</div> : <div className="empty-state">No audit events recorded.</div>}</section></AppShell>;
}