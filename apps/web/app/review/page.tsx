import Link from "next/link";
import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { Control, Regulation, ReviewQueue } from "../../lib/types";

export const dynamic = "force-dynamic";

export default async function ReviewPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["q", "state", "regulation_id", "section", "control_version_id", "min_confidence", "max_confidence", "sort"]) {
    const value = params[key]; if (typeof value === "string" && value) query.set(key, value);
  }
  const [result, regulationResult, controlResult] = await Promise.all([
    apiGet<ReviewQueue>(`/api/v1/review-queue?${query}`),
    apiGet<Regulation[]>("/api/v1/regulations"),
    apiGet<Control[]>("/api/v1/controls"),
  ]);
  const error = result.error ?? regulationResult.error ?? controlResult.error;
  const items = result.data?.items ?? [];
  return <main>
    <section className="masthead"><div><p className="eyebrow">HUMAN ASSURANCE</p><h1>Review queue</h1><p className="lede">Separate analyst decisions from machine-generated control suggestions.</p></div></section>
    <form className="workflowFilters">
      <label className="searchFilter">Search<input name="q" minLength={2} defaultValue={typeof params.q === "string" ? params.q : ""} placeholder="Requirement, evidence, or control" /></label>
      <label>State<select name="state" defaultValue={typeof params.state === "string" ? params.state : ""}><option value="">All states</option><option value="pending">Pending</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option><option value="deferred">Deferred</option><option value="confirmed_unmapped">Confirmed unmapped</option><option value="superseded">Superseded</option></select></label>
      <label>Regulation<select name="regulation_id" defaultValue={typeof params.regulation_id === "string" ? params.regulation_id : ""}><option value="">All regulations</option>{regulationResult.data?.map(regulation => <option value={regulation.id} key={regulation.id}>{regulation.source_key}</option>)}</select></label>
      <label>Section<input name="section" defaultValue={typeof params.section === "string" ? params.section : ""} placeholder="e.g. 4.2" /></label>
      <label>Control<select name="control_version_id" defaultValue={typeof params.control_version_id === "string" ? params.control_version_id : ""}><option value="">All controls</option>{controlResult.data?.map(control => <option value={control.version_id} key={control.version_id}>{control.control_key}</option>)}</select></label>
      <label>Confidence from<input name="min_confidence" type="number" min="0" max="1" step="0.01" defaultValue={typeof params.min_confidence === "string" ? params.min_confidence : ""} placeholder="0.00" /></label>
      <label>Confidence to<input name="max_confidence" type="number" min="0" max="1" step="0.01" defaultValue={typeof params.max_confidence === "string" ? params.max_confidence : ""} placeholder="1.00" /></label>
      <label>Sort<select name="sort" defaultValue={typeof params.sort === "string" ? params.sort : "confidence_asc"}><option value="confidence_asc">Lowest confidence</option><option value="confidence_desc">Highest confidence</option><option value="section">Regulation and section</option></select></label>
      <button className="secondary">Apply filters</button>
      <Link className="filterReset" href="/review">Clear</Link>
    </form>
    {error && <StatusMessage type="error">{error}</StatusMessage>}
    {!error && !items.length && <StatusMessage type="empty">No review items match the selected filters.</StatusMessage>}
    {!!items.length && <section className="dataSheet"><div className="sheetSummary"><span>{result.data?.total} review items</span><span>{items.filter(i => i.review_state === "pending").length} pending on this page</span></div><table><thead><tr><th>OBLIGATION</th><th>CONFIDENCE</th><th>CANDIDATES</th><th>REVIEW STATE</th></tr></thead><tbody>{items.map(item => <tr key={item.obligation.id}><td><span className="sectionNo">{item.regulation_key} / § {item.obligation.section_key}</span><Link href={`/obligations/${item.obligation.id}`}><b>{item.obligation.action}</b></Link></td><td>{Math.round(item.obligation.confidence * 100)}%</td><td>{item.candidates.length}<small className="tableSub">{item.candidates[0]?.control_key ?? "No proposed control"}</small></td><td><span className={`state ${item.review_state}`}>{item.review_state.replaceAll("_", " ")}</span></td></tr>)}</tbody></table></section>}
  </main>;
}
