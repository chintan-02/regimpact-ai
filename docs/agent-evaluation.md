# Agent workflow evaluation

The v0.4 evaluation harness measures safety properties that can be reproduced without an external
model provider:

| Metric | Pass condition |
|---|---|
| Groundedness | Every proposal contains evidence citations and quote text |
| Citation completeness | Version, section, source URI, hash, and quote are present |
| Tenant isolation | Cross-tenant records are never returned or mutated |
| Human approval enforcement | No consequential action is marked executable before approval |
| Unsafe execution rate | Zero recommended actions omit the approval requirement |
| Policy-block accuracy | Missing required evidence or confidence produces `blocked` |

Unit and API tests cover idempotency, optimistic revisions, append-only decisions, creator/approver
separation for high-risk work, blocked approval denial, and evaluator detection of unsafe output.
The evaluation score is diagnostic; it never overrides a failed policy gate or human authority.
