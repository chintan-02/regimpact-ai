import Link from "next/link";
import { StatusMessage } from "../components/StatusMessage";
import { getChangeRegister } from "../lib/api";

export const dynamic = "force-dynamic";

function shortDate(value: string | null | undefined) {
  if (!value) return "Not checked";
  return new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

type HomeProps = {
  searchParams: Promise<{ change?: string }>;
};

export default async function Home({ searchParams }: HomeProps) {
  const { change: selectedChangeId } = await searchParams;
  const { regulations, changes, sources, ingestions, selected } = await getChangeRegister(selectedChangeId);
  const error = regulations.error ?? changes.error ?? sources.error ?? ingestions.error;
  const completed = ingestions.data?.filter((job) => job.status === "completed").length ?? 0;
  const attention =
    ingestions.data?.filter((job) => ["failed", "dead_letter"].includes(job.status)).length ?? 0;

  return (
    <main>
      <section className="masthead">
        <div>
          <p className="eyebrow">REGULATORY CHANGE CONTROL</p>
          <h1>Change register</h1>
          <p className="lede">Review source revisions, evidence lineage, and downstream compliance impact.</p>
        </div>
        <div className="mastheadActions">
          <Link className="secondary buttonLink" href="/ingestions">View ingestion</Link>
          <Link className="primary buttonLink" href="/sources">Manage sources</Link>
        </div>
      </section>

      {error && <StatusMessage type="error">{error}</StatusMessage>}

      <section className="signalStrip" aria-label="Operational signals">
        <div><small>REGULATIONS</small><strong>{regulations.data?.length ?? "—"}</strong><span>Version-controlled records</span></div>
        <div><small>MONITORED SOURCES</small><strong>{sources.data?.filter((source) => source.enabled).length ?? "—"}</strong><span>Conditional source checks</span></div>
        <div><small>LATEST CHANGES</small><strong>{changes.data?.length ?? "—"}</strong><span>Across latest versions</span></div>
        <div className={attention ? "attention" : ""}><small>INGESTION HEALTH</small><strong>{attention || completed}</strong><span>{attention ? `${attention} require attention` : `${completed} completed`}</span></div>
      </section>

      {!error && changes.data?.length === 0 && (
        <StatusMessage type="empty">Add a regulation and ingest two document versions to create the first comparison.</StatusMessage>
      )}

      {changes.data && changes.data.length > 0 && (
        <section className="workspace">
          <div className="register">
            <div className="sectionHead">
              <div>
                <p className="eyebrow">LATEST REGULATORY CHANGES</p>
                <h2>{regulations.data?.length ?? 0} monitored {(regulations.data?.length ?? 0) === 1 ? "regulation" : "regulations"}</h2>
                <p className="sectionHint">Select a change to preview its impact.</p>
              </div>
              <span className="version">{changes.data.length} changes</span>
            </div>
            <div className="filters" aria-label="Change type legend"><span className="legend added">Added</span><span className="legend modified">Modified</span><span className="legend removed">Removed</span></div>
            <table>
              <thead><tr><th>SECTION</th><th>REGULATION</th><th>CHANGE</th><th>DETECTED</th></tr></thead>
              <tbody>{changes.data.map((change) => {
                const isSelected = change.id === selected.data?.id;
                const previewHref = `/?change=${encodeURIComponent(change.id)}`;
                return (
                <tr key={change.id} className={isSelected ? "current" : ""}>
                  <td><Link className="rowSelect" href={previewHref} aria-current={isSelected ? "true" : undefined}><span className="sectionNo">§ {change.section_key}</span><span className="changeHeading"><b>{change.heading}</b>{isSelected && <small className="selectedMarker">Selected</small>}</span></Link></td>
                  <td><Link className="rowSelect" href={previewHref}>{change.source_key}<small className="tableSub">{change.jurisdiction}</small></Link></td>
                  <td><Link className="rowSelect" href={previewHref}><span className={`change ${change.change_type}`}>{change.change_type}</span><small className="tableSub">v{change.previous_version_ordinal ?? "—"} → v{change.current_version_ordinal}</small></Link></td>
                  <td><Link className="rowSelect" href={previewHref}>{shortDate(change.detected_at)}</Link></td>
                </tr>
                );
              })}</tbody>
            </table>
          </div>

          <aside className="brief">
            {selected.data ? (
              <>
                <p className="eyebrow">SELECTED CHANGE / § {selected.data.section_key}</p>
                <h2>{selected.data.heading}</h2>
                <p className="summary">Compare the authoritative clauses and confirm whether obligations or controls require action.</p>
                <dl>
                  <div><dt>CHANGE TYPE</dt><dd>{selected.data.change_type}</dd></div>
                  <div><dt>VERSION PATH</dt><dd>v{selected.data.previous_version_ordinal ?? "—"} → v{selected.data.current_version_ordinal}</dd></div>
                  <div><dt>DETECTED</dt><dd>{shortDate(selected.data.detected_at)}</dd></div>
                </dl>
                <div className="evidence"><span>Current source lineage</span><b>{selected.data.source_key} / v{selected.data.current_citation.version_ordinal} / {selected.data.current_citation.page ? `p. ${selected.data.current_citation.page}` : "section removed"}</b><p>{selected.data.current_citation.source_uri}</p></div>
                <Link className="review buttonLink" href={`/changes/${selected.data.id}`}>Open investigation →</Link>
              </>
            ) : (
              <StatusMessage type={selected.error ? "error" : "empty"}>{selected.error ?? "Select a detected change to inspect its evidence."}</StatusMessage>
            )}
          </aside>
        </section>
      )}
    </main>
  );
}
