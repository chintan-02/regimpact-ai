import Link from "next/link";
import { StatusMessage } from "../../../components/StatusMessage";
import { apiGet } from "../../../lib/api";
import type { Control, ReviewQueue } from "../../../lib/types";

export const dynamic = "force-dynamic";

export default async function ControlDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [controls, reviews] = await Promise.all([apiGet<Control[]>("/api/v1/controls"), apiGet<ReviewQueue>("/api/v1/review-queue?limit=200")]);
  const control = controls.data?.find(item => item.id === id);
  if (!control) return <main><section className="masthead"><h1>Control unavailable</h1></section><StatusMessage type="error">{controls.error ?? "Control not found."}</StatusMessage></main>;
  if (reviews.error) return <main><section className="masthead"><div><p className="eyebrow">CONTROL DETAIL / {control.control_key}</p><h1>{control.title}</h1></div></section><StatusMessage type="error">{reviews.error}</StatusMessage></main>;
  const candidates = (reviews.data?.items ?? []).flatMap(item =>
    item.candidates
      .filter(candidate => candidate.control_version_id === control.version_id)
      .map(candidate => ({ candidate, review: item })),
  );
  return <main><section className="masthead"><div><p className="eyebrow">CONTROL DETAIL / {control.control_key}</p><h1>{control.title}</h1><p className="lede">Versioned ownership, evidence standard, and proposed obligation coverage.</p></div><Link className="secondary buttonLink" href="/controls">← Catalogue</Link></section><section className="detailWorkspace"><article className="evidencePanel"><p>{control.description}</p><dl><div><dt>VERSION</dt><dd>{control.ordinal}</dd></div><div><dt>OWNER</dt><dd>{control.owner}</dd></div><div><dt>EVIDENCE STANDARD</dt><dd>{control.evidence_requirement}</dd></div></dl></article><section className="coverageSheet"><div className="sheetSummary">{candidates.length} machine-generated candidates</div><table><thead><tr><th>OBLIGATION</th><th>SCORE</th><th>ANALYST STATE</th></tr></thead><tbody>{candidates.map(({ candidate, review }) => <tr key={candidate.id}><td><span className="sectionNo">{review.regulation_key} / § {review.obligation.section_key}</span><Link href={`/obligations/${candidate.obligation_id}`}><b>{review.obligation.action}</b></Link></td><td>{Math.round(candidate.score * 100)}%</td><td><span className={`state ${candidate.decision?.decision ?? "pending"}`}>{(candidate.decision?.decision ?? "pending").replaceAll("_", " ")}</span><small className="tableSub">Machine: {candidate.status.replaceAll("_", " ")}</small></td></tr>)}</tbody></table></section></section></main>;
}
