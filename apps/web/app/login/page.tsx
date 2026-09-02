"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [demoEnabled, setDemoEnabled] = useState(false);

  useEffect(() => {
    fetch("/api/auth/demo-status", { cache: "no-store" })
      .then((response) => response.json())
      .then((body: { enabled?: boolean }) => setDemoEnabled(Boolean(body.enabled)))
      .catch(() => setDemoEnabled(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    if (!response.ok) {
      setSubmitting(false);
      setError("The email or password is incorrect.");
      return;
    }
    router.replace("/");
    router.refresh();
  }

  async function demoLogin(role: "admin" | "analyst" | "viewer") {
    setSubmitting(true);
    setError(null);
    const response = await fetch("/api/auth/demo-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!response.ok) {
      setSubmitting(false);
      setError("Demo access is unavailable. Verify the local demo configuration and seed data.");
      return;
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <main className="loginShell">
      <section className="loginWorkspace" aria-labelledby="login-title">
        <div className="loginIntroduction"><p className="eyebrow">REGULATORY INTELLIGENCE</p><h1>Evidence before action.</h1><p>Trace regulatory change, assess downstream impact, and preserve accountable human decisions in one control room.</p><div className="loginAssurance"><span>Versioned evidence</span><span>Role-based authority</span><span>Append-only audit history</span></div></div>
        <div className="loginPanel">
          <p className="eyebrow">SECURE CONTROL ROOM</p>
          <h2 id="login-title">Sign in to RegImpact</h2>
          <p>Use your organization account to continue.</p>
          <form className="loginForm" onSubmit={submit}>
          <label htmlFor="email">Email</label>
          <input id="email" name="email" type="email" autoComplete="username" required />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            minLength={8}
            required
          />
          {error ? <p className="loginError" role="alert">{error}</p> : null}
          <button className="primaryButton" disabled={submitting} type="submit">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
          </form>
          {demoEnabled && <section className="demoAccess" aria-labelledby="demo-access-title"><div className="demoHeader"><div><p className="eyebrow">LOCAL DEMO</p><h3 id="demo-access-title">Explore by responsibility</h3></div><span>Non-production</span></div><div className="demoRoleGrid"><button disabled={submitting} onClick={() => demoLogin("admin")} type="button"><b>Administrator</b><small>Approve workflows, manage configuration and inspect operations.</small></button><button disabled={submitting} onClick={() => demoLogin("analyst")} type="button"><b>Analyst</b><small>Review obligations and create evidence-grounded proposals.</small></button><button disabled={submitting} onClick={() => demoLogin("viewer")} type="button"><b>Viewer</b><small>Inspect evidence and decision history with read-only access.</small></button></div></section>}
        </div>
      </section>
    </main>
  );
}
