"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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

  return (
    <main className="loginShell">
      <section className="loginPanel" aria-labelledby="login-title">
        <p className="eyebrow">SECURE CONTROL ROOM</p>
        <h1 id="login-title">Sign in to RegImpact</h1>
        <p>Use your organization account to access evidence and analyst workflows.</p>
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
      </section>
    </main>
  );
}
