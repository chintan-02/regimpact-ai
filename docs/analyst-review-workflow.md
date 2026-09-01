# Analyst review workflow

v0.2E preserves machine-generated mapping candidates and records analyst decisions in a separate append-only ledger. Decisions are tenant-scoped and retain obligation, control-version, actor, rationale, timestamp, revision, and supersession lineage.

Supported decisions are `accepted`, `rejected`, `deferred`, and `confirmed_unmapped`. Candidate decisions require a mapping identifier; confirmed-unmapped decisions apply to an obligation without selecting a candidate. Every write requires an explicit development actor, an idempotency key, and the expected current revision. A stale revision returns HTTP 409 and does not overwrite another analyst's work.

The `X-Actor-ID` header is a transparent development identity seam, not authentication. v0.3 must replace it with verified identity and authorization middleware without changing the decision service contract.

## Evaluation boundary

Mapping evaluation is separate from obligation-extraction evaluation. The v0.2E fixture contains eight curated engineering cases and measures recall and precision at configurable top-k, mean reciprocal rank, coverage, ambiguity, unmapped accuracy, and review workload. It is a deterministic regression suite, not production validation, and requires independent compliance-domain review before operational claims can be made.
