import Link from "next/link";
import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { Control, ControlMapping } from "../../lib/types";

export const dynamic = "force-dynamic";

export default async function ControlsPage() {
  const [controlResult, mappingResult] = await Promise.all([
    apiGet<Control[]>("/api/v1/controls"),
    apiGet<ControlMapping[]>("/api/v1/control-mappings?limit=500"),
  ]);
  const error = controlResult.error ?? mappingResult.error;
  const controls = controlResult.data ?? [];
  const mappings = mappingResult.data ?? [];
  const mappingCounts = mappings.reduce((counts, item) => {
    counts.set(item.control_version_id, (counts.get(item.control_version_id) ?? 0) + 1);
    return counts;
  }, new Map<string, number>());

  return (
    <main>
      <section className="masthead">
        <div>
          <p className="eyebrow">CONTROL ASSURANCE</p>
          <h1>Control catalogue</h1>
          <p className="lede">Review accountable owners, evidence standards, and proposed regulatory coverage.</p>
        </div>
      </section>
      {error && <StatusMessage type="error">{error}</StatusMessage>}
      {!error && controls.length === 0 && <StatusMessage type="empty">No controls are registered for this organization.</StatusMessage>}
      {controls.length > 0 && (
        <section className="controlGrid">
          {controls.map((control) => (
            <article className="controlCard" key={control.id}>
              <header><span>{control.control_key}</span><span>Version {control.ordinal}</span></header>
              <div><h2><Link href={`/controls/${control.id}`}>{control.title}</Link></h2><p>{control.description}</p></div>
              <dl>
                <div><dt>CONTROL OWNER</dt><dd>{control.owner}</dd></div>
                <div><dt>EVIDENCE STANDARD</dt><dd>{control.evidence_requirement}</dd></div>
                <div><dt>MAPPING CANDIDATES</dt><dd>{mappingCounts.get(control.version_id) ?? 0}</dd></div>
              </dl>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
