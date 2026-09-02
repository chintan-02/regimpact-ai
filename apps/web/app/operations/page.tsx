import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { OperationalSnapshot } from "../../lib/types";

export const dynamic = "force-dynamic";

function duration(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export default async function OperationsPage() {
  const result = await apiGet<OperationalSnapshot>("/api/v1/operations/snapshot");
  const data = result.data;
  const completed = data?.ingestions.completed ?? 0;
  const failed = (data?.ingestions.failed ?? 0) + (data?.ingestions.dead_letter ?? 0);
  return (
    <main>
      <section className="masthead">
        <div>
          <p className="eyebrow">PLATFORM OBSERVABILITY</p>
          <h1>Operations</h1>
          <p className="lede">Service traffic, ingestion reliability, and delivery backlog in one operational view.</p>
        </div>
      </section>
      {result.error && <StatusMessage type="error">{result.error}</StatusMessage>}
      {data && (
        <>
          <section className="signalStrip" aria-label="Platform health">
            <div><small>UPTIME</small><strong>{duration(data.uptime_seconds)}</strong><span>Current API process</span></div>
            <div><small>REQUESTS</small><strong>{data.requests.total}</strong><span>{data.requests.server_errors} server errors</span></div>
            <div className={failed ? "attention" : ""}><small>INGESTIONS</small><strong>{completed}</strong><span>{failed ? `${failed} require attention` : "No failures"}</span></div>
            <div className={data.outbox_pending || data.outbox_dead_letter ? "attention" : ""}><small>OUTBOX BACKLOG</small><strong>{data.outbox_pending}</strong><span>{data.outbox_dead_letter} dead-letter events</span></div>
          </section>
          <section className="dataSheet operationsSheet">
            <div className="sectionHead"><div><p className="eyebrow">RUNBOOK SIGNALS</p><h2>Runtime status</h2></div><span className="version">Live snapshot</span></div>
            <dl className="operationsGrid">
              <div><dt>API TRAFFIC</dt><dd>{data.requests.total} observed requests</dd><p>Prometheus metrics expose route, method, status, latency, in-flight requests, and uptime.</p></div>
              <div><dt>TRACE CORRELATION</dt><dd>W3C trace context active</dd><p>Every API response carries request and trace identifiers for cross-service investigation.</p></div>
              <div><dt>INGESTION PIPELINE</dt><dd>{completed} completed · {failed} failed</dd><p>Use the ingestion workspace to inspect failed or dead-letter work.</p></div>
              <div><dt>EVENT DELIVERY</dt><dd>{data.outbox_pending} pending events</dd><p>A sustained backlog indicates dispatcher or queue pressure.</p></div>
            </dl>
            <p className="snapshotTime">Snapshot generated {new Date(data.generated_at).toLocaleString("en-CA")}</p>
          </section>
        </>
      )}
    </main>
  );
}
