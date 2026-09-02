import { AgentWorkflowDecisionForm } from "../../components/AgentWorkflowDecisionForm";
import { AgentWorkflowStartForm } from "../../components/AgentWorkflowStartForm";
import { StatusMessage } from "../../components/StatusMessage";
import { apiGet } from "../../lib/api";
import type { AgentWorkflow, Obligation } from "../../lib/types";

export const dynamic = "force-dynamic";

export default async function WorkflowsPage() {
  const [runsResult, obligationsResult, userResult] = await Promise.all([
    apiGet<AgentWorkflow[]>("/api/v1/agent-workflows"),
    apiGet<Obligation[]>("/api/v1/obligations?limit=200"),
    apiGet<{ role: string }>("/api/v1/auth/me"),
  ]);
  const runs = runsResult.data ?? [];
  const role = userResult.data?.role;
  return (
    <main>
      <section className="masthead"><div><p className="eyebrow">CONTROLLED AGENTIC ASSURANCE</p><h1>Impact workflows</h1><p className="lede">Generate evidence-linked proposals, evaluate policy gates, and preserve human authority over every consequential decision.</p></div></section>
      {runsResult.error && <StatusMessage type="error">{runsResult.error}</StatusMessage>}
      {role !== "viewer" && obligationsResult.data && <section className="agentComposer"><div><p className="eyebrow">NEW ASSESSMENT</p><h2>Bounded objective</h2><p>The agent may analyze and propose. It cannot execute regulatory or control changes.</p></div><AgentWorkflowStartForm obligations={obligationsResult.data} /></section>}
      {!runsResult.error && runs.length === 0 && <StatusMessage type="empty">No controlled impact workflows have been created.</StatusMessage>}
      <section className="agentWorkflowGrid">{runs.map((run) => {
        const passed = Object.values(run.policy_results).filter(Boolean).length;
        const policies = Object.entries(run.policy_results);
        return <article className="agentWorkflowCard" key={run.id}>
          <header><div><span className={`state ${run.status}`}>{run.status.replaceAll("_", " ")}</span><span className="riskLabel">{run.risk_level} risk</span></div><code>{run.agent_version}</code></header>
          <div className="agentWorkflowBody"><p className="eyebrow">OBJECTIVE</p><h2>{run.goal}</h2><blockquote>{run.evidence.quote}</blockquote><p className="citation">§ {run.evidence.section_key} · v{run.evidence.version_ordinal} · {run.evidence.page ? `page ${run.evidence.page}` : "page unavailable"} · <a href={run.evidence.source_uri}>source evidence</a></p>
            <h3>{run.proposal.summary}</h3><ul>{run.proposal.recommended_actions.map((action) => <li key={`${run.id}-${action.control_key}`}><b>{action.control_key}</b> · {action.action.replaceAll("_", " ")} · owner {action.owner}</li>)}</ul>
            <div className="policyGrid">{policies.map(([name, value]) => <span className={value ? "pass" : "stop"} key={name}>{value ? "PASS" : "STOP"} · {name.replaceAll("_", " ")}</span>)}</div>
            <p className="evaluationScore">Policy evaluation: {passed}/{policies.length} gates · score {Math.round(run.evaluation_score * 100)}%</p>
            {run.latest_decision && <div className={`decisionRecord ${run.latest_decision.decision}`}><b>Latest human decision: {run.latest_decision.decision.replaceAll("_", " ")}</b><p>{run.latest_decision.rationale}</p><small>{run.latest_decision.actor_id} · revision {run.latest_decision.revision}</small></div>}
            {role === "admin" && <AgentWorkflowDecisionForm blocked={run.status === "blocked"} revision={run.revision} runId={run.id} />}
            {role !== "admin" && <p className="readOnlyNotice">Only an administrator may approve, reject, or request changes.</p>}
          </div>
        </article>;
      })}</section>
    </main>
  );
}
