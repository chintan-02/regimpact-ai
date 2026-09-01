"use client";

import { useState } from "react";

export function ReviewDecisionForm({ obligationId, mappingId, revision }: { obligationId: string; mappingId: string | null; revision: number }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(formData: FormData) {
    setBusy(true);
    setMessage("");
    const decision = String(formData.get("decision"));
    const rationale = String(formData.get("rationale"));
    const query = mappingId ? `?mapping_id=${mappingId}` : "";
    try {
      const response = await fetch(`/api/reviews/${obligationId}${query}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, rationale, expected_revision: revision, idempotency_key: crypto.randomUUID() }),
      });
      if (response.status === 409) setMessage("Conflict: another analyst updated this review. Refresh before deciding.");
      else if (!response.ok) setMessage("Decision was not saved. Check the rationale and try again.");
      else setMessage("Decision recorded with evidence lineage and audit history.");
    } catch { setMessage("The API is unavailable. Your decision was not saved."); }
    finally { setBusy(false); }
  }

  return (
    <form className="decisionForm" action={submit}>
      <label>Decision<select name="decision" defaultValue={mappingId ? "deferred" : "confirmed_unmapped"}>
        {mappingId && <><option value="accepted">Accept candidate</option><option value="rejected">Reject candidate</option><option value="deferred">Defer review</option></>}
        {!mappingId && <option value="confirmed_unmapped">Confirm unmapped</option>}
      </select></label>
      <label>Reviewer rationale<textarea name="rationale" minLength={3} maxLength={2000} required placeholder="Record the evidence-based reason for this disposition." /></label>
      <button className="primary" disabled={busy}>{busy ? "Recording…" : "Record decision"}</button>
      {message && <p className="formStatus" role="status">{message}</p>}
    </form>
  );
}
