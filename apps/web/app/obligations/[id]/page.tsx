import Link from "next/link";
import { ReviewDecisionForm } from "../../../components/ReviewDecisionForm";
import { StatusMessage } from "../../../components/StatusMessage";
import { apiGet } from "../../../lib/api";
import type { ReviewItem } from "../../../lib/types";

export const dynamic = "force-dynamic";

const explanationStopwords = new Set(["a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with"]);

export default async function ObligationDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await apiGet<ReviewItem>(`/api/v1/review-queue/${id}`);
  if (result.error || !result.data) return <main><section className="masthead"><h1>Obligation unavailable</h1></section><StatusMessage type="error">{result.error ?? "Review item not found."}</StatusMessage></main>;
  const item = result.data;
  return <main>
    <section className="masthead"><div><p className="eyebrow">OBLIGATION DETAIL / {item.regulation_key} / § {item.obligation.section_key}</p><h1>{item.obligation.heading}</h1><p className="lede">Exact evidence, extraction lineage, and candidate-control comparison.</p></div><Link className="secondary buttonLink" href="/review">← Review queue</Link></section>
    <section className="detailWorkspace"><article className="evidencePanel"><p className="eyebrow">AUTHORITATIVE EVIDENCE</p><blockquote>{item.obligation.evidence_quote}</blockquote><dl><div><dt>SOURCE</dt><dd><a href={item.obligation.source_uri}>{item.regulation_title}</a></dd></div><div><dt>LINEAGE</dt><dd>Version {item.obligation.version_ordinal} · § {item.obligation.section_key} · {item.obligation.page ? `Page ${item.obligation.page}` : "Page unavailable"}</dd></div><div><dt>EXTRACTION</dt><dd>{item.obligation.extraction_method} · {item.obligation.calibration_policy_id}</dd></div><div><dt>CONFIDENCE</dt><dd>{Math.round(item.obligation.confidence * 100)}% {item.obligation.requires_review ? "· analyst validation required" : "· above review threshold"}</dd></div></dl></article>
    <div className="candidateStack">{item.candidates.map(candidate => {
      const materialTerms = candidate.explanation.matched_terms?.filter(
        term => !explanationStopwords.has(term.toLowerCase()),
      ) ?? [];
      return <article className="candidateCard" key={candidate.id}><header><div><span className="sectionNo">{candidate.control_key}</span><h2>{candidate.control_title}</h2></div><strong>{Math.round(candidate.score * 100)}%</strong></header><p>Material matched terms: {materialTerms.join(", ") || "No material shared terms recorded"}</p><p><b>Machine state:</b> {candidate.status.replaceAll("_", " ")} · {candidate.mapping_method}</p>{candidate.decision && <div className={`decisionRecord ${candidate.decision.decision}`}><b>Latest analyst decision: {candidate.decision.decision.replaceAll("_", " ")}</b><p>{candidate.decision.rationale}</p><small>{candidate.decision.actor_id} · revision {candidate.decision.revision}</small></div>}<ReviewDecisionForm obligationId={item.obligation.id} mappingId={candidate.id} revision={candidate.decision?.revision ?? 0} /></article>;
    })}{!item.candidates.length && <article className="candidateCard"><h2>No candidate controls</h2><p>Confirm this obligation as unmapped only after checking the current control catalogue.</p><ReviewDecisionForm obligationId={item.obligation.id} mappingId={null} revision={item.obligation_revision} /></article>}</div></section>
  </main>;
}
