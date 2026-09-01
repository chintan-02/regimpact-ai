import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { Source } from "../../lib/types";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  const result = await apiGet<Source[]>("/api/v1/sources");
  return (
    <main>
      <section className="masthead"><div><p className="eyebrow">SOURCE GOVERNANCE</p><h1>Regulatory sources</h1><p className="lede">Manage authoritative publications, monitoring cadence, and collection health.</p></div></section>
      {result.error && <StatusMessage type="error">{result.error}</StatusMessage>}
      {result.data?.length === 0 && <StatusMessage type="empty">No regulatory sources are configured.</StatusMessage>}
      {result.data && result.data.length > 0 && <section className="dataSheet"><div className="sheetSummary"><span>{result.data.length} approved sources</span><span>{result.data.filter((source) => source.enabled).length} active</span><span>{result.data.filter((source) => source.last_error_code).length} exceptions</span></div><table><thead><tr><th>SOURCE</th><th>HOST</th><th>CADENCE</th><th>NEXT CHECK</th><th>HEALTH</th></tr></thead><tbody>{result.data.map((source) => <tr key={source.id}><td><b>{source.name}</b><small className="tableSub">{source.url}</small></td><td>{source.allowed_host}</td><td>{source.poll_interval_minutes === 1440 ? "Daily" : `${source.poll_interval_minutes} min`}</td><td>{new Date(source.next_check_at).toLocaleString("en-CA")}</td><td><span className={`state ${source.last_error_code ? "failed" : "healthy"}`}>{source.last_error_code ? "Attention" : source.enabled ? "Monitoring" : "Paused"}</span><small className="tableSub">{source.consecutive_failures === 0 ? "No collection failures" : `${source.consecutive_failures} consecutive failures`}</small></td></tr>)}</tbody></table></section>}
    </main>
  );
}
