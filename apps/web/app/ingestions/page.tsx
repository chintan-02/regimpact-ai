import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { Ingestion } from "../../lib/types";

export const dynamic = "force-dynamic";

export default async function IngestionsPage() {
  const result = await apiGet<Ingestion[]>("/api/v1/ingestions?limit=100");
  return (
    <main>
      <section className="masthead"><div><p className="eyebrow">DOCUMENT OPERATIONS</p><h1>Ingestion ledger</h1><p className="lede">Track document provenance, processing outcomes, and version creation.</p></div></section>
      {result.error && <StatusMessage type="error">{result.error}</StatusMessage>}
      {result.data?.length === 0 && <StatusMessage type="empty">No documents have entered the ingestion pipeline.</StatusMessage>}
      {result.data && result.data.length > 0 && <section className="dataSheet"><div className="sheetSummary"><span>{result.data.length} ingestion records</span><span>{result.data.filter((job) => job.status === "completed").length} completed</span><span>{result.data.filter((job) => ["failed", "dead_letter"].includes(job.status)).length} exceptions</span></div><table><thead><tr><th>DOCUMENT</th><th>STATE</th><th>SIZE</th><th>CONTENT IDENTITY</th><th>RECEIVED</th></tr></thead><tbody>{result.data.map((job) => <tr key={job.id}><td><b>{job.original_filename}</b><small className="tableSub">{job.media_type}</small></td><td><span className={`state ${job.status}`}>{job.status.replace("_", " ")}</span>{job.error_code && <small className="tableSub">{job.error_code}</small>}</td><td>{(job.size_bytes / 1024).toFixed(1)} KB</td><td><code>{job.content_hash.slice(0, 16)}…</code></td><td>{new Date(job.created_at).toLocaleString("en-CA")}</td></tr>)}</tbody></table></section>}
    </main>
  );
}
