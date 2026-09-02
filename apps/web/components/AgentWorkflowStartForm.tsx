"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Obligation } from "../lib/types";

export function AgentWorkflowStartForm({ obligations }: { obligations: Obligation[] }) {
  const router = useRouter();
  const [obligationId, setObligationId] = useState(obligations[0]?.id ?? "");
  const [goal, setGoal] = useState("Assess downstream control impact using authoritative evidence.");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const response = await fetch("/api/agent-workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ obligation_id: obligationId, goal, idempotency_key: crypto.randomUUID() }),
    });
    const body = await response.json();
    setBusy(false);
    if (!response.ok) {
      setMessage(body.detail ?? "Workflow could not be started.");
      return;
    }
    setMessage("Evidence-grounded proposal created. Human approval is still required.");
    router.refresh();
  }

  return (
    <form className="agentStartForm" onSubmit={submit}>
      <label>Obligation<select onChange={(event) => setObligationId(event.target.value)} value={obligationId}>{obligations.map((item) => <option key={item.id} value={item.id}>§ {item.section_key} · {item.heading}</option>)}</select></label>
      <label>Controlled objective<textarea onChange={(event) => setGoal(event.target.value)} required minLength={10} value={goal} /></label>
      <button className="primaryButton" disabled={busy || !obligationId} type="submit">{busy ? "Evaluating…" : "Create impact proposal"}</button>
      {message && <p className="formStatus">{message}</p>}
    </form>
  );
}
