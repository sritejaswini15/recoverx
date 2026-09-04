const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type RecoveryCase = {
  id: string;
  customer_id: string;
  customer: string;
  customer_phone?: string;
  customer_email?: string;
  customer_reliability?: number;
  preferred_channel?: string;
  preferred_language?: string;
  event_type: string;
  amount: number;
  currency: string;
  risk_score: number;
  recovery_probability: number;
  expected_recovery_value: number;
  ai_confidence: number;
  policy_decision: string;
  recommended_action: string;
  status: string;
  contact_attempts: number;
  recovered_amount: number;
  action_executed: boolean;
  failure_reason?: string;
  created_at: string;
  updated_at?: string;
  // Detail fields returned by GET /recovery-cases/{id}
  diagnosis?: string;
  root_cause?: string;
  ai_reasoning?: string;
  payment_link?: {
    id: string;
    provider_link_id: string;
    amount: number;
    status: string;
    short_url?: string;
    payment_url?: string | null;
  } | null;
  communications?: Array<{
    id: string;
    channel: string;
    direction: string;
    content: string;
    status: string;
    created_at: string;
  }>;
  escalation?: {
    id: string;
    reason: string;
    resolution?: string;
    resolution_notes?: string;
  } | null;
  promises_to_pay?: Array<{
    id: string;
    amount: number;
    promised_date: string;
    status: string;
    fulfilled: boolean;
  }>;
};

export type IntegrationEntry = {
  name: string;
  category: string;
  status: "CONNECTED" | "SIMULATED" | "NOT_CONFIGURED";
  label: string;
  detail: string;
};

export type IntegrationStatus = {
  integrations: IntegrationEntry[];
  counts: { total: number; simulated: number; connected: number; not_configured: number };
};

export type Analytics = {
  revenue_at_risk: number;
  revenue_targeted: number;
  revenue_recovered: number;
  recovery_rate: number;
  expected_recovery_value?: number;
  cases: number;
  successful_recoveries: number;
  escalations?: number;
  stopped_cases?: number;
  average_recovery_time_hours?: number;
  average_ai_confidence?: number;
  policy_violations?: number;
  action_failures?: number;
  false_escalations?: number;
  funnel: {
    risk_cases: number;
    eligible: number;
    actions: number;
    successful: number;
  };
  mode: string;
};

export type Strategy = {
  strategy: string;
  attempts: number;
  success: number;
  recovered: number;
  recovery_rate?: number;
  average_recovery_time?: number;
};

export type AuditEvent = {
  event_name: string;
  case_id?: string;
  payload?: Record<string, unknown>;
  created_at: string;
};

export type Customer = {
  id: string;
  name: string;
  email: string;
  phone: string;
  lifetime_value: number;
  successful_payments: number;
  failed_payments: number;
  payment_reliability_pct: number;
  preferred_channel: string;
  preferred_language: string;
  historical_recovery_rate: number;
};

export type PaymentRequest = {
  case_id: string;
  customer_name: string;
  customer_email: string;
  amount: number;
  currency: string;
  status: string;
  recovered_amount: number;
  event_type: string;
  failure_reason: string;
  recommended_action: string;
  payment_link?: { id: string; short_url: string; amount: number; status: string } | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window === "undefined" ? null : window.localStorage.getItem("recoverx_access_token");
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.localStorage.removeItem("recoverx_access_token");
      window.location.replace("/login");
    }
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) => request<{ access_token: string; user: { name: string; email: string; role: string } }>("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) }),
  logout: async () => {
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } catch {
      // Ignore network errors on logout
    } finally {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem("recoverx_access_token");
        window.localStorage.removeItem("recoverx_user");
        window.location.replace("/login");
      }
    }
  },
  analytics: () => request<Analytics>("/analytics/recovery"),
  cases: (limit = 100) => request<{ items: RecoveryCase[]; total: number }>(`/recovery-cases?limit=${limit}`),
  customers: (limit = 100) => request<{ items: Customer[]; total: number }>(`/customers?limit=${limit}`),
  caseById: (caseId: string) => request<RecoveryCase>(`/recovery-cases/${caseId}`),
  customer: (customerId: string) => request<Customer>(`/customers/${customerId}`),
  strategies: () => request<Strategy[]>("/analytics/strategy-performance"),
  audit: (limit = 10, caseId?: string) => {
    const query = caseId ? `&case_id=${encodeURIComponent(caseId)}` : "";
    return request<{ items: AuditEvent[]; total: number }>(`/audit-events?limit=${limit}${query}`);
  },
  executeCase: (caseId: string) => request<{ case_id: string; status: string; policy?: string; recovered_amount?: number }>(`/recovery-cases/${caseId}/execute`, { method: "POST" }),
  approveCase: (caseId: string) => request<{ case_id: string; status: string }>(`/recovery-cases/${caseId}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resolution: "APPROVE" }) }),
  stopCase: (caseId: string) => request<{ case_id: string; status: string }>(`/recovery-cases/${caseId}/stop`, { method: "POST" }),
  simulatePayment: (caseId: string) => request<{ case_id: string; status: string; recovered_amount: number }>("/simulation/payment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }) }),
  simulateFailure: (caseId: string) => request<{ case_id: string; status: string }>("/simulation/failure", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }) }),
  simulateEvent: (eventType: string, customerId: string, amount: number) => request<{ event_id: string; case_id: string | null; status: string | null }>("/simulation/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ event_type: eventType, customer_id: customerId, amount, currency: "INR" }) }),
  resolveEscalation: (caseId: string, resolution: string) => request<{ case_id: string; status: string }>(`/escalations/${caseId}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resolution }) }),
  policy: () => request<{ max_auto_action_amount: number; human_approval_above_amount: number; max_contact_attempts: number; escalate_after_days: number; min_ai_confidence: number; preferred_channels: string; supported_languages: string }>("/policies"),
  updatePolicy: (policy: { max_auto_action_amount: number; human_approval_above_amount: number; max_contact_attempts: number; escalate_after_days: number; min_ai_confidence: number; preferred_channels: string; supported_languages: string }) => request<typeof policy>("/policies", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(policy) }),
  runBatch: (count = 500, seed = 20260902) => request<Record<string, unknown>>("/demo/run-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count, seed }),
  }),
  integrationStatus: () => request<IntegrationStatus>("/integrations/status"),
  simulateOptOut: (customerId: string) => request<{ customer_id: string; opted_out: boolean }>("/simulation/opt-out", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ customer_id: customerId }) }),
  simulateTimeout: (caseId: string) => request<{ case_id: string; status: string }>("/simulation/timeout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }) }),
  simulateLowConfidence: (caseId: string) => request<{ case_id: string; status: string }>("/simulation/low-confidence", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }) }),
  simulateMaxAttempts: (caseId: string) => request<{ case_id: string; status: string }>("/simulation/max-attempts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }) }),
  simulateInvalidAi: (caseId: string) => request<{ case_id: string; status: string }>("/simulation/invalid-ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }) }),
  simulatePromise: (caseId: string, amount: number, promisedDate: string) => request<{ case_id: string; promise_id: string }>("/simulation/promise-to-pay", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId, amount, promised_date: promisedDate }) }),
  publicPaymentRequest: (caseId: string) => request<PaymentRequest>(`/pay/${caseId}`),
  submitPublicPayment: (caseId: string, action: "pay" | "promise", promiseDate?: string) => request<{ status: string; recovered_amount?: number; promise_id?: string; promised_date?: string; message?: string }>(`/pay/${caseId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId, action, promise_date: promiseDate }) }),
  escalationCount: () => request<{ total: number; items: RecoveryCase[] }>("/recovery-cases?status=ESCALATED&limit=500").then((r) => r.total),
};

export function formatInr(value: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

export function initials(name: string) {
  return name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

export function labelForEvent(eventType: string) {
  return eventType.replaceAll("_", " ").toLowerCase().replace(/(^| )\w/g, (letter) => letter.toUpperCase());
}
