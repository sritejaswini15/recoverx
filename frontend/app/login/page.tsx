"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../../lib/api-client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@recoverx.local");
  const [password, setPassword] = useState("recoverx-demo");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await api.login(email, password);
      window.localStorage.setItem("recoverx_access_token", result.access_token);
      window.localStorage.setItem("recoverx_user", JSON.stringify(result.user));
      router.push("/");
    } catch {
      setError("Invalid credentials. Check the email and password, then retry.");
    } finally {
      setLoading(false);
    }
  };
  return <main className="login-page"><section className="login-card"><div className="brand login-brand"><span className="brand-mark">R</span><span>recover<span className="brand-x">X</span></span></div><p className="eyebrow">AI REVENUE RECOVERY CONTROL PLANE</p><h1>Sign in to RecoverX</h1><p className="login-subtitle">Operate recovery workflows with policy, context, and measurable outcomes.</p><form onSubmit={submit}><label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>{error && <div className="error-state" role="alert">{error}</div>}<button className="primary-button" type="submit" disabled={loading}>{loading ? "Signing in..." : "Sign in"}</button></form><small className="login-note">Demo environment · role permissions are enforced by the API</small></section></main>;
}