"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, formatInr, type PaymentRequest } from "../../../lib/api-client";

const REASON_LABELS: Record<string, string> = {
  PAYMENT_FAILURE: "Payment could not be processed",
  SUBSCRIPTION_HALTED: "Subscription payment failed",
  INVOICE_OVERDUE: "Invoice is overdue",
  CHECKOUT_ABANDONED: "Checkout was not completed",
  PAYMENT_LINK_ABANDONED: "Payment link was not completed",
};

export default function CustomerPayPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [data, setData] = useState<PaymentRequest | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [promiseMode, setPromiseMode] = useState(false);
  const [promiseDate, setPromiseDate] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      const json = await api.publicPaymentRequest(caseId);
      setData(json);
      if (json.status === "RECOVERED") { setDone(true); setNotice("✅ Payment already received. Thank you!"); }
      if (json.status === "STOPPED" || json.status === "EXPIRED") { setError("This payment request has been closed."); }
    } catch {
      setError("Unable to load payment details. Please try again.");
    }
  }, [caseId]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(initialLoad);
  }, [load]);

  const pay = async () => {
    if (!caseId || !data) return;
    setLoading("pay");
    setNotice("");
    try {
      const json = await api.submitPublicPayment(caseId, "pay");
      setData({ ...data, status: json.status, recovered_amount: json.recovered_amount ?? data.recovered_amount });
      if (json.status === "RECOVERED") {
        setDone(true);
        setNotice("✅ Payment received! Your case has been resolved. Thank you.");
      } else {
        setNotice(json.message ?? "Payment processed.");
      }
    } catch {
      setNotice("Payment failed. Please check your connection and try again.");
    } finally {
      setLoading(null);
    }
  };

  const promise = async () => {
    if (!caseId || !data) return;
    setLoading("promise");
    setNotice("");
    try {
      const json = await api.submitPublicPayment(caseId, "promise", promiseDate);
      setData({ ...data, status: json.status });
      setDone(true);
      setNotice(`✅ Promise to Pay recorded for ${new Date(json.promised_date ?? promiseDate).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}. We'll send a reminder closer to the date.`);
    } catch {
      setNotice("Could not record promise. Please try again.");
    } finally {
      setLoading(null);
      setPromiseMode(false);
    }
  };

  if (error) {
    return (
      <div className="pay-shell">
        <div className="pay-card error-card">
          <span className="pay-logo">R<span>X</span></span>
          <h1>Payment Not Available</h1>
          <p>{error}</p>
          <p className="pay-help">Questions? Contact us at <a href="mailto:support@recoverx.io">support@recoverx.io</a></p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="pay-shell">
        <div className="pay-card">
          <span className="pay-logo">R<span>X</span></span>
          <p className="pay-loading">Loading payment details…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="pay-shell">
      <div className="pay-card">
        <div className="pay-header">
          <span className="pay-logo">R<span>X</span></span>
          <span className="pay-powered">Powered by RecoverX</span>
        </div>

        {done ? (
          <div className="pay-success">
            <div className="pay-success-icon">✓</div>
            <h1>Thank you, {data.customer_name.split(" ")[0]}!</h1>
            <p>{notice}</p>
            <div className="pay-amount-done">{formatInr(data.recovered_amount || data.amount)}</div>
          </div>
        ) : (
          <>
            <div className="pay-greeting">
              <p className="pay-hi">Hi {data.customer_name.split(" ")[0]},</p>
              <p className="pay-reason">{REASON_LABELS[data.event_type] ?? data.failure_reason}</p>
            </div>

            <div className="pay-amount-block">
              <span className="pay-label">Amount Due</span>
              <strong className="pay-amount">{formatInr(data.amount)}</strong>
            </div>

            {data.payment_link && (
              <div className="pay-link-badge">
                <span>💳</span>
                <span>Payment link ready</span>
                <span className={`pstatus pstatus-${data.payment_link.status}`}>{data.payment_link.status.toUpperCase()}</span>
              </div>
            )}

            {notice && <div className="pay-notice" role="alert">{notice}</div>}

            {!promiseMode ? (
              <div className="pay-actions">
                <button
                  className="pay-btn-primary"
                  onClick={pay}
                  disabled={loading !== null}
                >
                  {loading === "pay" ? "Processing payment…" : `Pay ${formatInr(data.amount)} Now`}
                </button>
                <button
                  className="pay-btn-secondary"
                  onClick={() => setPromiseMode(true)}
                  disabled={loading !== null}
                >
                  Promise to Pay
                </button>
              </div>
            ) : (
              <div className="pay-promise-form">
                <p>When can you make the payment?</p>
                <label>
                  Payment date
                  <input
                    type="date"
                    value={promiseDate}
                    min={new Date().toISOString().slice(0, 10)}
                    onChange={(e) => setPromiseDate(e.target.value)}
                  />
                </label>
                <div className="pay-actions">
                  <button className="pay-btn-primary" onClick={promise} disabled={loading !== null}>
                    {loading === "promise" ? "Recording…" : "Confirm Promise to Pay"}
                  </button>
                  <button className="pay-btn-secondary" onClick={() => setPromiseMode(false)} disabled={loading !== null}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <p className="pay-security">🔒 Secured by Simulated Razorpay · RecoverX</p>
          </>
        )}
      </div>
    </div>
  );
}
