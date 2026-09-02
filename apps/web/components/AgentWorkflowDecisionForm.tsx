"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function AgentWorkflowDecisionForm({ runId, revision, blocked }: { runId: string; revision: number; blocked: boolean }) {
  const router = useRouter();
  const [decision, setDecision] = useState("approved");
  const [rationale, setRationale] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    const response = await fetch(`/api/agent-workflows/${runId}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, rationale, expected_revision: revision, idempotency_key: crypto.randomUUID() }),
    });
    const body = await response.json();
    setBusy(false);
    if (!response.ok) {
      setMessage(body.detail ?? "Decision could not be recorded.");
      return;
    }
    setMessage("Human decision recorded in append-only audit history.");
    setRationale("");
    router.refresh();
  }

  return (
    <form className="decisionForm" onSubmit={submit}>
      <label>Decision<select onChange={(event) => setDecision(event.target.value)} value={decision}><option disabled={blocked} value="approved">Approve proposal</option><option value="changes_requested">Request changes</option><option value="rejected">Reject proposal</option></select></label>
      <label>Approval rationale<textarea minLength={12} onChange={(event) => setRationale(event.target.value)} required value={rationale} /></label>
      <button className="primaryButton" disabled={busy} type="submit">{busy ? "Recording…" : "Record human decision"}</button>
      {message && <p className="formStatus">{message}</p>}
    </form>
  );
}
