import Link from "next/link";
import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { Obligation, ReviewQueue } from "../../lib/types";

export const dynamic = "force-dynamic";

function confidenceLabel(value: number) {
  return `${Math.round(value * 100)}%`;
}

export default async function ObligationsPage() {
  const [obligationResult, reviewResult] = await Promise.all([
    apiGet<Obligation[]>("/api/v1/obligations?limit=500"),
    apiGet<ReviewQueue>("/api/v1/review-queue?limit=200"),
  ]);
  const error = obligationResult.error ?? reviewResult.error;
  const obligations = obligationResult.data ?? [];
  const reviewsByObligation = new Map(
    (reviewResult.data?.items ?? []).map((item) => [item.obligation.id, item]),
  );
  const reviewCount = obligations.filter((item) => item.requires_review).length;
  const withoutCandidatesCount = obligations.filter(
    (item) => !reviewsByObligation.get(item.id)?.candidates.length,
  ).length;

  return (
    <main>
      <section className="masthead">
        <div>
          <p className="eyebrow">REQUIREMENT ASSURANCE</p>
          <h1>Obligation register</h1>
          <p className="lede">Validate extracted requirements, confidence, evidence, and control coverage.</p>
        </div>
      </section>
      {error && <StatusMessage type="error">{error}</StatusMessage>}
      {!error && obligations.length === 0 && <StatusMessage type="empty">No obligations have been extracted from the current regulation versions.</StatusMessage>}
      {obligations.length > 0 && (
        <section className="dataSheet obligationSheet">
          <div className="sheetSummary"><span>{obligations.length} obligations</span><span>{reviewCount} require review</span><span>{withoutCandidatesCount} without candidates</span></div>
          <table>
            <thead><tr><th>REQUIREMENT</th><th>CLASSIFICATION</th><th>CONFIDENCE</th><th>CONTROL STATUS</th><th>EVIDENCE</th></tr></thead>
            <tbody>{obligations.map((item) => {
              const review = reviewsByObligation.get(item.id);
              const accepted = review?.candidates.find(
                (candidate) => candidate.decision?.decision === "accepted",
              );
              const candidate = accepted ?? review?.candidates[0];
              const displayState = accepted ? "accepted" : review?.review_state ?? candidate?.status;
              return (
                <tr key={item.id}>
                  <td><span className="sectionNo">§ {item.section_key} · v{item.version_ordinal}</span><Link href={`/obligations/${item.id}`}><b>{item.action}</b></Link><small className="tableSub">{item.heading}</small></td>
                  <td><b>{item.modality}</b><small className="tableSub">{item.subject ?? "Responsible party not resolved"}</small></td>
                  <td><span className={`confidence ${item.requires_review ? "review" : "accepted"}`}>{confidenceLabel(item.confidence)}</span><small className="tableSub">{item.requires_review ? "Analyst validation required" : "Above review threshold"}</small></td>
                  <td>{candidate ? <><span className={`state ${displayState}`}>{displayState?.replaceAll("_", " ")}</span><small className="tableSub">{candidate.control_key} · {candidate.control_title}</small></> : <><span className="state unmapped">Unmapped</span><small className="tableSub">No control candidate recorded</small></>}</td>
                  <td><blockquote>{item.evidence_quote}</blockquote><small className="tableSub">{item.page ? `Page ${item.page}` : "Page unavailable"}</small></td>
                </tr>
              );
            })}</tbody>
          </table>
        </section>
      )}
    </main>
  );
}
