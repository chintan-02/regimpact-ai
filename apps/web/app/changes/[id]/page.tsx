import Link from "next/link";
import { StatusMessage } from "../../../components/StatusMessage";
import { apiGet } from "../../../lib/api";
import type { ChangeDetail, Obligation } from "../../../lib/types";

export const dynamic = "force-dynamic";

export default async function ChangePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await apiGet<ChangeDetail>(`/api/v1/changes/${id}`);
  if (result.error || !result.data) return <main><section className="masthead"><div><p className="eyebrow">INVESTIGATION</p><h1>Change unavailable</h1></div></section><StatusMessage type="error">{result.error ?? "The requested change could not be found."}</StatusMessage></main>;
  const change = result.data;
  const obligationResult = await apiGet<Obligation[]>(`/api/v1/obligations?version_id=${change.current_citation.version_id}&limit=500`);
  const obligations = obligationResult.data?.filter((item) => item.section_key === change.section_key) ?? [];
  return (
    <main>
      <section className="masthead"><div><p className="eyebrow">INVESTIGATION / {change.source_key} / § {change.section_key}</p><h1>{change.heading}</h1><p className="lede">Evidence-preserving comparison of regulatory source versions.</p></div><Link className="secondary buttonLink" href="/">← Change register</Link></section>
      <section className="diffMeta"><span className={`change ${change.change_type}`}>{change.change_type}</span><b>v{change.previous_version_ordinal ?? "—"} → v{change.current_version_ordinal}</b><span>{change.jurisdiction}</span></section>
      <section className="diffWorkspace">
        <article className="diffPane previous"><header><span>PREVIOUS CLAUSE</span><b>Version {change.previous_citation?.version_ordinal ?? "—"} · {change.previous_citation?.page ? `Page ${change.previous_citation.page}` : "Not present"}</b></header><p>{change.previous_text ?? "No corresponding clause appears in the previous version."}</p>{change.previous_citation && <footer>{change.previous_citation.source_uri}</footer>}</article>
        <article className="diffPane currentVersion"><header><span>CURRENT CLAUSE</span><b>Version {change.current_citation.version_ordinal} · {change.current_citation.page ? `Page ${change.current_citation.page}` : "Removed"}</b></header><p>{change.current_text ?? "The clause is not present in the current version."}</p><footer>{change.current_citation.source_uri}</footer></article>
      </section>
      <section className="impactPanel">
        <div><p className="eyebrow">IMPACT ASSESSMENT</p><h2>{change.change_type === "removed" ? "Retirement review required" : `${obligations.length} extracted ${obligations.length === 1 ? "obligation" : "obligations"}`}</h2><p>{change.change_type === "removed" ? "Confirm that dependent procedures, controls, and retained evidence are no longer required before closing this change." : "Validate the extracted requirements and review their proposed control coverage before approval."}</p></div>
        <div className="impactActions"><span className={`state ${change.change_type === "removed" || obligations.some((item) => item.requires_review) ? "needs_review" : "healthy"}`}>{change.change_type === "removed" || obligations.some((item) => item.requires_review) ? "Review required" : "Ready for mapping"}</span><Link className="primary buttonLink" href="/obligations">Review obligations</Link></div>
      </section>
    </main>
  );
}
