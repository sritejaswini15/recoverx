"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "../../components/app-shell";
import { api, formatInr, initials } from "../../lib/api-client";
import type { Customer } from "../../lib/api-client";

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.customers().then((result) => setCustomers(result.items)).catch(() => setError("Unable to load customers."));
  }, []);

  return <AppShell title="Customers"><div className="route-heading"><div><p className="eyebrow">CUSTOMER RECOVERY INTELLIGENCE</p><h1>Customers</h1><p className="subheading">Prioritize outreach using persisted payment history and recovery behavior.</p></div><Link className="secondary-button" href="/cases">View cases</Link></div>{error && <div className="error-state" role="alert">{error}</div>}<section className="panel route-panel"><div className="panel-header"><h2>Recovery profiles</h2><span className="muted">{customers.length} loaded</span></div>{customers.length ? <div className="case-table wide-table"><div className="table-row table-head"><span>Customer</span><span>Lifetime value</span><span>Payments</span><span>Reliability</span><span>Preferred recovery</span></div>{customers.map((customer) => <div className="table-row case-row" key={customer.id}><span className="customer-cell"><span className="customer-avatar">{initials(customer.name)}</span><span><b>{customer.name}</b><small>{customer.email}</small></span></span><span>{formatInr(customer.lifetime_value)}</span><span>{customer.successful_payments} successful · {customer.failed_payments} failed</span><span>{customer.payment_reliability_pct}%</span><span>{customer.preferred_channel} · {customer.preferred_language}</span></div>)}</div> : <div className="empty-state">No customer profiles found.</div>}</section></AppShell>;
}