# ADR: Companion API integration contract

Status: accepted; RegImpact first-release controls implemented

Date: 2026-11-15

Decision owners: RegImpact application, platform security, data governance, and future
companion teams

## Context and evidence convention

This ADR defines the governed, read-only API boundary for a future, separately deployed
`regimpact-companion`. It builds on `docs/companion-phase-0-audit.md`,
`docs/adr/companion-authentication-contract.md`, and
`docs/adr/companion-token-exchange-decision.md`. It does not claim that the companion
or every control in this target contract already exists.

The following labels are used throughout:

- **Current -- verified** describes behavior present in this repository.
- **Decision** defines the integration contract that must be implemented before use.
- **Recommendation** defines a preferred implementation where a final operator or
  business choice remains.
- **Unresolved** identifies a decision that is deliberately not made here.

Repository references use `path::symbol` when a specific symbol is material. All
paths are relative to the repository root.

## Decision summary

The first companion release will use only human-delegated, read-only calls. The
companion will obtain a Microsoft Entra access token for the exact RegImpact API
audience through OAuth 2.0 On-Behalf-Of (OBO). A browser token is never forwarded to
the companion or RegImpact API. RegImpact will authorize each request by intersecting
token, registered-client, local identity, local role, organization, and resource
ownership controls. No token claim creates a RegImpact permission.

No app-only RegImpact data capability is approved for the first release. The
companion's managed identity or confidential-client credential may authenticate the
companion as the OBO client, but that fact does not authorize an app-only data call.
Any later application permission requires a new allowlist decision, an application
role, a local service grant, tenant-isolation tests, and separate audit policy.

Existing domain queries are exposed to the companion only through the implemented
scope/client intersection, durable read audit, bounded pagination, rate limiting, and
canonical citation controls described below.

## Implementation status

**Implemented in RegImpact:** migration `20261115_0014` adds tenant-bound delegated
client grants; `apps/api/src/regimpact/companion_access.py` enforces the exact
route/scope allowlist, emergency shutdown, Redis rate limit and safe auditing;
`apps/api/src/regimpact/companion_grant_cli.py` provides controlled offline grant
lifecycle commands; collection routes are bounded; search is readiness-gated; and
`GET /api/v1/evidence/{section_id}` resolves hash-bound canonical evidence.
Review/workflow and every mutation route remain excluded.

**Deferred to `regimpact-companion`:** browser PKCE login, companion-audience
validation, OBO acquisition/cache, answer generation, claim-support evaluation and
the companion runtime/deployment. Azure registrations, managed identities, private
networking and live tenant consent remain operator work and are not provisioned here.

## Trust boundary

### Current -- verified

- The API is mounted under `/api/v1`; the console currently reads a
  `regimpact_access_token` cookie server-side and forwards that bearer token to
  FastAPI (`apps/api/src/regimpact/main.py::create_app`;
  `apps/web/lib/api.ts::apiGet`).
- Validated Entra user tokens retain delegated scopes and application roles as
  distinct metadata on `CurrentUser`. Current route dependencies use only local roles:
  `Authenticated` admits active `viewer`, `analyst`, and `admin` users;
  `ReviewerUser` admits `analyst` and `admin`; `AdminUser` admits only `admin`
  (`apps/api/src/regimpact/auth.py::CurrentUser`, `require_roles`, `Authenticated`,
  `ReviewerUser`, `AdminUser`).
- Entra authentication currently accepts a user principal only, resolves an active
  external mapping to an active local user and organization, and does not accept a
  service principal (`apps/api/src/regimpact/token_validation.py::_validate_entra`;
  `apps/api/src/regimpact/auth.py::get_current_user`).
- Azure exposes the Next.js console externally while the FastAPI app has internal
  ingress. No companion workload, identity, or network boundary exists in the
  template (`infra/main.bicep::web`, `api`, `identity`).

### Decision

The RegImpact console, companion API/runtime, and RegImpact API are separate resource
servers and security principals:

1. The browser authenticates to the console/BFF. Browser credentials or console
   session tokens are not RegImpact API credentials and must never be passed through
   the companion.
2. The console calls the companion with a companion-audience token. The companion
   validates that token, then performs OBO to obtain a new delegated access token with
   the exact RegImpact API audience.
3. RegImpact validates the OBO token's issuer, audience, signature, lifetime,
   principal type, delegated scope, authorized client, tenant, and immutable identity
   before applying local authorization.
4. A non-human companion call, if approved in a later phase, uses a distinct managed
   identity or confidential client and application roles. It must never impersonate a
   human or reuse a delegated token.
5. Successful authentication is only the first gate. It grants no organization,
   role, record, or operation by itself.

The selected issuer, audiences, signing and validation rules remain those in
`docs/adr/companion-token-exchange-decision.md`; the local identity and authorization
rules remain those in `docs/adr/companion-authentication-contract.md`.

## Authorization algorithm

Every companion request must pass all applicable checks below, in this order. A
missing, ambiguous, inactive, mismatched, or unconfigured value fails closed.

1. Validate the token for the exact RegImpact API audience and configured Entra
   tenant; do not retry it as a legacy token after Entra classification.
2. Identify the principal type. A route must explicitly allow either a delegated user
   or an application principal; principal types are never interchangeable.
3. For a delegated call, require the route's delegated scope. For an application
   call, require the route's application role. `scp` and `roles` remain distinct.
4. Require a server-side client grant binding the calling `azp`/client ID, principal
   type, route capability, and organization or approved tenant boundary. Tenant-wide
   consent alone is insufficient.
5. For a delegated user, resolve one active external-identity mapping for the exact
   provider, issuer tenant, and immutable external object identity.
6. Require the mapped local user and organization membership to be active.
7. Apply the existing local RBAC dependency for the route.
8. Derive the organization from the local principal or service grant, never from a
   caller-supplied organization header, query, `oid`, `sub`, group, scope, or role.
9. Apply the existing organization predicate and resource ownership check to every
   primary and related record.
10. Emit the required authorization/audit outcome and propagate correlation context.

The effective permission is therefore:

`valid token AND principal type AND scope/application role AND client grant AND
identity/service mapping AND active local principal AND organization membership AND
local RBAC AND resource ownership`.

`scp`, `roles`, groups, `oid`, `sub`, email, or an Entra directory role must never
independently grant a local RegImpact role or permission. Current tests already prove
that exposed scopes and application roles do not add local RBAC permissions; the
companion-specific client and route intersection still needs implementation
(`apps/api/tests/test_token_validation.py`).

## Delegated read capability allowlist

### Status definitions

- **Reusable**: the existing endpoint and all cross-cutting controls satisfy this
  contract unchanged.
- **Reusable with restriction**: the existing tenant-scoped query and schema are a
  valid basis, but the endpoint is not approved until the listed restriction and the
  common companion controls are implemented.
- **Missing**: no current endpoint supplies the required capability or contract.

All current read routes below use `Authenticated`, directly or through an organization
dependency, so their local RBAC floor remains `viewer`. For validated Entra calls,
`get_current_user` now invokes the exact client, route, scope, tenant grant, rate-limit
and audit boundary in `apps/api/src/regimpact/companion_access.py`
(`apps/api/src/regimpact/auth.py::Authenticated`;
`apps/api/src/regimpact/api.py::organization_header`;
`apps/api/src/regimpact/controls_api.py::organization_header`;
`apps/api/src/regimpact/review_api.py::organization_header`). The delegated scope is an
additional intersection, not a replacement for local RBAC. Legacy console behavior is
unchanged unless the explicitly configured companion client is used.

| Capability | Method and current path | Implementation | Current local RBAC | Proposed delegated scope | Tenant/ownership rule | Current response schema | Current pagination/filtering | Required companion audit | Status and restriction |
|---|---|---|---|---|---|---|---|---|---|
| Regulations | `GET /api/v1/regulations` | `apps/api/src/regimpact/api.py::list_regulations` | `Authenticated` | `regulations:read` | Query filters `RegulationRecord.organization_id` to the mapped local organization | `list[RegulationListItem]` | `limit` 1--200 (default 100), `offset`; title/ID order | Outcome, local actor/org, client, route and correlation | Reusable: companion enforcement, pagination and durable audit implemented |
| Regulation versions | `GET /api/v1/regulations/{regulation_id}/versions` | `apps/api/src/regimpact/api.py::list_versions` | `Authenticated` | `regulations:read` | `SqlAlchemyVersionRepository.owned_regulation` verifies the parent organization before listing its versions | `list[VersionSummary]` | `limit` 1--200 (default 100), `offset`; ordinal/ID order | As above plus regulation ID | Reusable: bounded, audited and hash-versioned |
| Sections and source text | `GET /api/v1/evidence/{section_id}` | `apps/api/src/regimpact/api.py::get_canonical_evidence` | `Authenticated` | `evidence:read` | Resolves exact organization/version/section chain and rejects hash/version mismatch as not found | `CanonicalEvidenceResponse` | Single resource; required version and content hashes; bounded body | Stable IDs, scope, route, outcome and correlation; no body | Reusable: canonical hash-bound evidence resolver implemented |
| Version differences | `GET /api/v1/changes` | `apps/api/src/regimpact/api.py::list_changes` | `Authenticated` | `changes:read` | Join to `RegulationRecord` and filter its organization; optional regulation filter remains within that boundary | `list[ChangeRegisterItem]` | `regulation_id`, `latest_only`; `limit` 1--200 (default 100), `offset` | Filters, returned change IDs/count, local actor/org/client and correlation | Reusable with restriction: common controls and a durable read audit |
| Version difference detail | `GET /api/v1/changes/{change_id}` | `apps/api/src/regimpact/api.py::get_change` | `Authenticated` | `changes:read` | Change is joined to an organization-owned regulation; absent and foreign IDs share not-found behavior | `ChangeDetail` with previous/current text and `CitationResponse` | Single resource | Change/version IDs and outcome; do not duplicate text in audit | Reusable with restriction: citation lacks section/regulation/content-hash identity |
| Obligations | `GET /api/v1/obligations` | `apps/api/src/regimpact/api.py::list_obligations` | `Authenticated` | `evidence:read` | Join through regulation and filter its organization | `list[ObligationResponse]` | `regulation_id`, `version_id`, `status`; `limit` 1--200 (default 100), `offset` | Filters, route outcome and correlation | Reusable: version and section hashes included |
| Clause classifications | `GET /api/v1/clause-classifications` | `apps/api/src/regimpact/api.py::list_clause_classifications` | `Authenticated` | Not allowlisted | Join through regulation and filter its organization | `list[ClauseClassificationResponse]` | Internal route contract unchanged | None for companion because access is denied | Reusable with restriction but deferred: governance approval and companion-safe presentation are still required |
| Controls | `GET /api/v1/controls` | `apps/api/src/regimpact/controls_api.py::list_controls` | `Authenticated` | `controls:read` | Filters active controls by organization and returns latest version | `list[ControlResponse]` | `limit` 1--200 (default 100), `offset`; control-key/ID order | Route outcome and correlation | Reusable: bounded and audited |
| Obligation-control mappings | `GET /api/v1/control-mappings` | `apps/api/src/regimpact/controls_api.py::list_control_mappings` | `Authenticated` | `controls:read` | Filters mapping, obligation and control organizations | `list[ControlMappingListItem]` | Obligation/control-version filters; `limit` 1--200, `offset`; score/ID order | Route outcome and correlation | Reusable: bounded related-resource ownership enforced |
| Hybrid/semantic search | `GET /api/v1/search` | `apps/api/src/regimpact/api.py::search_regulatory_evidence`; `apps/api/src/regimpact/retrieval.py::hybrid_search` | `Authenticated` | `evidence:read` | Search and readiness queries constrain organization and model | `HybridSearchResponse` with complete version/section hashes | `q` length 2--500; `limit` 1--50 | Normalized query hash, route outcome and correlation; never raw query/body | Reusable after operator provisions the production provider and complete index; readiness and rate limits fail closed |
| Canonical evidence/citation resolution | `GET /api/v1/evidence/{section_id}` | `apps/api/src/regimpact/api.py::get_canonical_evidence` | `Authenticated` | `evidence:read` | Organization/version/section and related obligation/control chains are verified | `CanonicalEvidenceResponse` | Required version ID/hash and section hash; single bounded response | Stable IDs, route outcome and correlation | Reusable: stale, mismatched and foreign references are not found |
| Review queue status | `GET /api/v1/review-queue` | `apps/api/src/regimpact/review_api.py::review_queue` | `Authenticated` | `reviews:read` | `_review_items` builds only records for the mapped organization | `ReviewQueueResponse` | State, regulation, section, control, text, confidence and sort filters; `limit` 1--200 (default 50), `offset`; total | Filters, returned obligation IDs/count, client and correlation; no rationale/evidence text | Reusable with restriction and not in the minimum release: data is operationally sensitive and filtering currently materializes the organization's queue in memory |
| Review item status | `GET /api/v1/review-queue/{obligation_id}` | `apps/api/src/regimpact/review_api.py::review_detail` | `Authenticated` | `reviews:read` | Lookup occurs only within organization-scoped `_review_items`; foreign IDs are not found | `ReviewQueueItem` | Single resource | Obligation ID and outcome; omit evidence/rationale text from audit | Reusable with restriction and not in the minimum release: expose only after review-data governance approval |
| Controlled workflow status | `GET /api/v1/agent-workflows` | `apps/api/src/regimpact/agent_api.py::list_workflows` | `Authenticated` | `workflows:read` | Filters `AgentWorkflowRunRecord.organization_id` | `list[AgentWorkflowResponse]` | `limit` 1--200 (default 100); newest first; no offset | Returned run/obligation IDs/count and outcome | Reusable with restriction and not in the minimum release: response includes plan, evidence, proposal, policy results, creator and latest decision; add pagination and governance approval |
| Controlled workflow detail | `GET /api/v1/agent-workflows/{run_id}` | `apps/api/src/regimpact/agent_api.py::get_workflow` | `Authenticated` | `workflows:read` | Filters run ID and organization; foreign IDs are not found | `AgentWorkflowResponse` | Single resource | Run/obligation IDs and outcome; no plan/evidence/proposal content in audit | Reusable with restriction and not in the minimum release: same sensitivity and common-control requirements |

`RegulationListItem`, `VersionSummary`, `CitationResponse`, `ChangeDetail`,
`ObligationResponse`, `ClauseClassificationResponse`, `RetrievalHitResponse`,
`ControlResponse`, `ControlMappingListItem`, `ReviewQueueResponse`, and
`AgentWorkflowResponse` are defined in `apps/api/src/regimpact/schemas.py`.

### Minimum delegated release

**Decision:** the initial endpoint allowlist is limited to regulations, versions,
changes, change detail, obligations, controls, control mappings, bounded search, and a
new canonical evidence resolver. Clause classifications may be enabled only if the UI
labels them as model output. Review queue and workflow reads are disabled until a data
governance owner approves their content and purpose. The allowlist is exact: a valid
scope does not authorize any route absent from the registered client grant.

## Application and service-principal capability

### Decision for the first release

The application/service-principal data allowlist is empty. No current background use
case requires the companion to read RegImpact without a human. The companion's
managed identity or confidential-client credential is used to authenticate the OBO
client and protect its token cache; it is not an application permission.

Current Entra validation deliberately requires a user principal and cannot be treated
as app-only support (`apps/api/src/regimpact/token_validation.py::_validate_entra`;
`apps/api/tests/test_token_validation.py`). The existing shared Azure managed identity
is also not an acceptable future companion authorization boundary
(`infra/main.bicep::identity`).

### Future gate

If a scheduled, non-human read is later justified, it must receive a companion-specific
managed identity, a dedicated application role, an explicit local service grant with
organization and capability restrictions, and a route allowlist smaller than or equal
to the delegated allowlist. The candidate `Evidence.Read.All` role in
`docs/adr/companion-authentication-contract.md` remains unassigned and does not exist
as an implemented grant. Application roles must never map to `AdminUser`,
`ReviewerUser`, or a synthetic human.

## Explicitly prohibited operations

The companion must not call, proxy, automate, or receive a grant for:

- approve, reject, override, accept, or otherwise record mapping or workflow
  decisions (`apps/api/src/regimpact/review_api.py::create_decision`;
  `apps/api/src/regimpact/agent_api.py::record_workflow_decision`);
- create, version, modify, or suggest mappings or controls
  (`apps/api/src/regimpact/controls_api.py::create_control`, `suggest_control_mappings`);
- create regulations or versions, initiate/replay ingestion, mutate monitored sources,
  run extraction/classification/indexing, or invoke queue/system operations
  (`apps/api/src/regimpact/api.py`);
- create, disable, list, or otherwise administer external identities or users
  (`apps/api/src/regimpact/auth_api.py`);
- assign or infer local roles, permissions, organizations, or memberships;
- access another organization, including by supplying a foreign record ID;
- connect directly to PostgreSQL, blob storage, a vector index, a queue, or an
  internal worker/dispatcher/scheduler interface (`apps/api/src/regimpact/tasks.py`;
  `apps/api/src/regimpact/dispatcher.py`;
  `apps/api/src/regimpact/scheduler.py`);
- issue unrestricted arbitrary search, raw SQL, vector queries, or bulk corpus export;
  only the bounded, tenant-scoped search contract above is eligible; or
- automatically promote a model, index, mapping, decision, workflow proposal, or
  generated answer to production state.

The unauthenticated calibration policy and operational health/metrics surfaces are not
companion data capabilities and are excluded from the allowlist
(`apps/api/src/regimpact/api.py::calibration_policy`;
`apps/api/src/regimpact/main.py::create_app`).

## Retrieval and citation contract

### Current -- verified

- Search indexing stores a SHA-256 content hash for the indexed section text and is
  idempotent for an existing section/model pair. Search constrains both lexical and
  semantic candidates by organization and embedding model
  (`apps/api/src/regimpact/retrieval.py::index_version`, `hybrid_search`;
  `apps/api/tests/test_retrieval.py`).
- `RetrievalHitResponse` exposes section, regulation and version IDs, section key,
  heading/body, page, source URI, version ordinal, model ID, and ranking scores, but
  not the version or indexed-content hash
  (`apps/api/src/regimpact/schemas.py::RetrievalHitResponse`).
- `CitationResponse` for a change exposes version ID/ordinal, page and source URI, but
  not regulation ID, section/change ID, or version hash
  (`apps/api/src/regimpact/schemas.py::CitationResponse`;
  `apps/api/src/regimpact/api.py::get_change`).
- `VersionSummary` does expose the version `content_hash`; obligation and
  classification responses provide source/version/section context but omit that hash
  (`apps/api/src/regimpact/schemas.py::VersionSummary`, `ObligationResponse`,
  `ClauseClassificationResponse`).
- Retrieval tests verify deterministic indexing, tenant isolation, and source lineage;
  read tests verify change citation lineage and not-found behavior across tenants
  (`apps/api/tests/test_retrieval.py`;
  `apps/api/tests/test_read_api.py`).

### Decision: canonical citation identity

Every factual companion answer must retain, and the UI must be able to resolve, this
minimum citation identity:

- server-derived organization ID;
- regulation ID and version ID;
- version ordinal and immutable version content hash;
- section/clause ID and human-readable section key;
- source locator: source URI plus page when available, with a future bounded character
  or structural locator if exact-page resolution is insufficient;
- obligation, control, control-version, mapping, change, classification, review, or
  workflow IDs when that object is the evidence being described; and
- retrieval model ID and lexical/vector/combined scores only as diagnostic ranking
  metadata.

The resolver must re-check the current local organization and resource chain on every
request. A cached citation is not authority to fetch a record after access, mapping,
membership, or source state changes. Companion cache keys must include organization,
version hash, and stable evidence ID; content from different organizations must never
share a cache entry.

### Citation validity versus claim support

These are separate controls:

- **Citation validity** asks whether the cited IDs exist, belong to the caller's
  organization, resolve to the stated immutable version/content hash and source
  locator, and have not been mixed across versions. RegImpact can provide and verify
  this lineage.
- **Claim support** asks whether the cited passage actually entails or adequately
  supports the companion's generated statement. A valid source pointer does not prove
  the claim. Retrieval rank, vector similarity, model confidence, classification,
  mapping score, or the presence of an evidence quote is not proof.

The companion owns claim-to-passage evaluation, answer construction, uncertainty and
conflict handling, and refusal when support is insufficient. RegImpact owns canonical
records, tenant-safe resolution, hashes, and lineage. Answers must preserve multiple
citations when a claim depends on multiple passages and must never present search
scores as legal or compliance confidence.

## Operational contract

### Pagination and bounded results

**Decision:** companion collection reads use stable ordering, default page size 100,
and a hard page size of 200. Search uses its current default 10 and hard maximum 50.
The API must reject larger requests with `422`; it must not silently clamp them.
All companion collection routes now enforce this bound. Excluded classification,
review and workflow routes retain their separate internal contracts. Offset
pagination is retained initially, but every companion endpoint
must have deterministic tie-break ordering. New or high-churn collections should use
opaque cursors. The response shape and total-count policy must be documented before
the client is generated.

Current companion bounds are consistent: collection reads cap at 200 and search caps
at 50 (`apps/api/src/regimpact/api.py::list_regulations`, `list_versions`,
`list_changes`, `list_obligations`, `search_regulatory_evidence`;
`apps/api/src/regimpact/controls_api.py::list_controls`, `list_control_mappings`;
`apps/api/tests/test_read_api.py`; `apps/api/tests/test_controls_api.py`).

### Timeouts, retries, and idempotency

- **Recommendation:** the companion uses a 10-second total deadline for ordinary
  reads and 20 seconds for search, always less than the caller's end-to-end deadline.
  Final values require load testing and an operator SLO decision. Current FastAPI code
  has no route-level companion timeout middleware.
- Retry only connection failures, safe read timeouts where no response was received,
  and `408`, `429`, `502`, `503`, or `504`. Honor `Retry-After`; use exponential
  backoff with jitter and at most two retries inside the deadline.
- Do not retry `400`, `401`, `403`, `404`, `409`, or `422` automatically. A refreshed
  token permits one new attempt after `401` only when the normal token-acquisition
  policy says the token expired; repeated `401` fails closed.
- Allowlisted `GET` operations are safe and idempotent and do not use idempotency keys.
  A retry may observe newer data, so version/content hashes remain part of evidence
  identity. No mutation becomes allowed merely because it accepts an idempotency key.

### Correlation, observability, and audit

- The companion sends a bounded opaque `X-Request-ID` and valid W3C `traceparent`.
  RegImpact returns `X-Request-ID`, `X-Trace-ID`, `traceparent`, and response time.
  Current middleware already creates/propagates these values and records low-cardinality
  route metrics, but it does not bound or validate the incoming request-ID value
  (`apps/api/src/regimpact/main.py::request_context`;
  `apps/api/src/regimpact/observability.py`).
- Each allowed or denied companion call requires a safe audit/security record with
  timestamp, local organization and actor IDs when known, registered client ID,
  principal type, capability/scope or application-role name, method, route template,
  decision/reason category, status, bounded resource/result IDs, request/trace IDs,
  and duration. Search audits store a one-way hash of the normalized query, result IDs,
  count and model ID rather than raw query text.
- Durable `AuditEventRecord` has organization, actor, event/entity identity, JSON
  detail and timestamp. Authorized companion reads and post-identity denials now write
  safe companion events through `apps/api/src/regimpact/companion_access.py`
  (`apps/api/src/regimpact/db_models.py::AuditEventRecord`). Denials before an
  organization is known require a separate security sink with the same correlation
  guarantees.
- Logs and audit events must never contain bearer tokens, authorization headers,
  cookies, secrets, assertion tokens, claim dumps, `oid`, `sub`, email, raw evidence
  bodies, review rationales, workflow plans/proposals, or raw search queries. Scope and
  application-role *names used in the authorization decision* are permitted; raw claim
  payloads are not.
- Metrics use route templates, outcome classes, principal type and registered client
  category only; they must not use organization, user, resource, query, or token
  values as metric labels.

### Rate limiting

**Implemented:** RegImpact enforces Redis-backed limits by registered client,
organization and capability, with a distinct search budget, bounded Redis timeout,
generic `503` on limiter failure, deterministic `429` and `Retry-After`
(`apps/api/src/regimpact/companion_access.py`).

The companion also limits each user/session, but its limit does not replace the API
limit. A rejected request returns `429` with the standard error envelope and
`Retry-After`; it does not disclose another tenant's utilization. Exact production
quotas remain an operator/SLO decision and must be load-tested. The emergency client
shutdown is `REGIMPACT_COMPANION_ACCESS_ENABLED=false`.

### Versioning and compatibility

`/api/v1` is the current versioned prefix (`apps/api/src/regimpact/api.py::router`;
`apps/api/src/regimpact/controls_api.py::router`;
`apps/api/src/regimpact/review_api.py::router`;
`apps/api/src/regimpact/agent_api.py::router`). After the companion contract is
approved, additive optional fields may be added to v1; removing/renaming fields,
changing meaning, tightening an accepted enum, changing pagination shape, or changing
authorization semantics requires a new version or an approved migration window. CI
must detect OpenAPI changes against an approved contract snapshot. Deprecation notice
and support-window length remain operator decisions.

## Error model

Current handlers return an envelope containing `error.code`, `error.message`, and
`request_id`; validation may add bounded details. `401` maps to `unauthenticated`,
`403` to `forbidden`, validation to `request_validation_failed` or `invalid_input`,
missing records to `not_found`, conflicts to `resource_conflict`, and a scanner
dependency failure to `503` (`apps/api/src/regimpact/main.py::create_app`).

The companion contract is:

| Status | Meaning and required behavior | Retry |
|---|---|---|
| `401` | Missing, malformed, expired, wrong-audience/issuer, unmapped, or otherwise invalid authentication. Use one generic message and `WWW-Authenticate`; never reveal validation internals or mapping existence. | Only one attempt after ordinary token refresh; otherwise no |
| `403` | Authenticated principal lacks principal-type permission, scope/role, client grant, active local authorization, or route policy. Do not reveal which foreign organization or grant exists. | No |
| `404` | Resource is absent or is outside the caller's organization/ownership boundary. These cases must be indistinguishable. | No |
| `422` | Query/path input or page bound violates the public contract. Details may name invalid public fields but not internal records or policy. | No, until corrected |
| `429` | Client/organization/capability rate limit exceeded. Include bounded `Retry-After`; no tenant utilization details. | Yes, after `Retry-After` and within deadline |
| `502`, `503`, `504` | A required dependency or gateway is unavailable/timed out. Return a generic message and correlation ID; do not expose connection strings, hosts, model payloads, or stack traces. | Yes, bounded and jittered |
| `500` | Unexpected server failure. Return a generic envelope and correlation ID; investigate server-side. | No automatic retry unless an operator classifies the failure as transient |

The current exception path logs unexpected failures but lacks an explicit documented
generic JSON `500` handler; the companion boundary must verify this response in tests
before exposure (`apps/api/src/regimpact/main.py::request_context`).

## Gap analysis

### A. Existing capabilities reusable without changing domain behavior

The following implementation behavior can be reused behind the new cross-cutting
boundary:

- organization predicates and foreign-as-not-found behavior in regulation/version,
  change, obligation, classification, control, mapping, review and workflow reads
  (`apps/api/src/regimpact/api.py`; `apps/api/src/regimpact/controls_api.py`;
  `apps/api/src/regimpact/review_api.py`; `apps/api/src/regimpact/agent_api.py`);
- active local-user and external-identity resolution for delegated Entra users
  (`apps/api/src/regimpact/auth.py::get_current_user`;
  `apps/api/src/regimpact/external_identities.py`);
- distinct storage of delegated scopes and application roles without new grants
  (`apps/api/src/regimpact/auth.py::CurrentUser`;
  `apps/api/tests/test_token_validation.py`);
- tenant-constrained indexing/search and stable regulation/version/section identifiers
  (`apps/api/src/regimpact/retrieval.py`;
  `apps/api/tests/test_retrieval.py`); and
- request/trace propagation, structured logging and route metrics
  (`apps/api/src/regimpact/main.py::request_context`;
  `apps/api/src/regimpact/observability.py`).

These are reusable internals, not approval to expose the current routes unchanged.

### B. RegImpact changes implemented for companion integration

The blocking rows below are implemented by migration `20261115_0014`,
`apps/api/src/regimpact/companion_access.py`, the allowlisted routes, canonical
evidence resolver, Redis limiter and their focused tests. The production embedding
provider/backfill, private deployment, OpenAPI artifact gate and live OBO test remain
deployment or companion work; they must still pass the acceptance gates before live
traffic.

| Priority | Required change | Likely implementation files | Required or extended tests |
|---|---|---|---|
| Blocking | Add a route-capability dependency that intersects principal type, delegated scope/application role, registered client grant, local RBAC and organization. Keep existing resource predicates. Do not infer grants from token claims. | `apps/api/src/regimpact/auth.py`, `apps/api/src/regimpact/config.py`, allowlisted route modules under `apps/api/src/regimpact/`; a persistent grant model/migration only if grants are database-managed | Extend `apps/api/tests/test_auth.py`, `apps/api/tests/test_token_validation.py`; add companion authorization matrix tests covering missing/wrong scope, client, principal type, inactive user/mapping, local role, organization and foreign resource |
| Blocking | Define and enforce the exact delegated route allowlist. All app-only routes remain denied. | `apps/api/src/regimpact/api.py`, `controls_api.py`, and only after approval `review_api.py`, `agent_api.py` | Route-by-route allow/deny tests plus negative tests for every write/admin endpoint |
| Blocking | Add uniform deterministic pagination and companion page caps; add missing filters/offsets where necessary. | `apps/api/src/regimpact/api.py`, `apps/api/src/regimpact/controls_api.py`, `apps/api/src/regimpact/agent_api.py`, `apps/api/src/regimpact/schemas.py` | Extend `apps/api/tests/test_read_api.py`, `test_controls_api.py`, `test_agent_workflow.py`; boundary, ordering and tenant tests |
| Blocking | Add canonical tenant-safe evidence resolution and complete citation identity, including version/content hash. | `apps/api/src/regimpact/schemas.py`, `apps/api/src/regimpact/api.py`, `apps/api/src/regimpact/retrieval.py`; reuse repository ownership helpers | Extend `apps/api/tests/test_retrieval.py`, `test_read_api.py`; add stale/hash mismatch, foreign ID and citation-resolution tests |
| Blocking | Add durable authorized/denied companion read auditing and safe pre-tenant security events; bind them to request/trace/client context and prove rollback-independent denials where needed. | `apps/api/src/regimpact/auth.py`, `apps/api/src/regimpact/main.py`, `apps/api/src/regimpact/observability.py`, `apps/api/src/regimpact/db_models.py`; migration only if structured columns are chosen | Extend `apps/api/tests/test_observability.py`, `test_auth.py`; add successful, denied, foreign-resource, search-redaction, durability and no-secret tests |
| Blocking | Add API-side client/organization/capability rate limiting with `429` and `Retry-After`, plus emergency client disable. | `apps/api/src/regimpact/main.py`, `apps/api/src/regimpact/config.py`, a small dedicated limiter component; Azure settings later | Add limiter isolation, burst, reset, retry-header, search-budget and fail-closed dependency tests |
| Blocking | Make production search deployable and observable: approved embedding provider/dependency, index coverage/readiness, bounded query policy and failure semantics. Current non-local configuration is not complete. | `apps/api/src/regimpact/embeddings.py`, `apps/api/src/regimpact/config.py`, `apps/api/pyproject.toml`, `apps/api/Dockerfile`, `infra/main.bicep` | Extend `apps/api/tests/test_retrieval.py` and configuration tests; add provider failure, stale/missing index and readiness tests |
| Recommended | Bound/validate incoming request IDs and guarantee a generic JSON `500` envelope. | `apps/api/src/regimpact/main.py` | Extend `apps/api/tests/test_observability.py` and API error tests |
| Recommended | Snapshot and compatibility-check the companion OpenAPI subset. | API OpenAPI generation/CI documentation tooling; no route behavior change required | Contract snapshot/diff check and generated-client smoke test |

OBO token acquisition is deliberately not a RegImpact API change: the future
companion is the confidential client and obtains its RegImpact-audience token. The API
validates that token and enforces the registered `azp` client grant.

### C. Features that belong only in `regimpact-companion`

- Companion-audience authentication and session/API boundary.
- OBO token acquisition, encrypted in-memory token cache, refresh discipline, and
  single-flight acquisition; no browser-token passthrough or persisted bearer tokens.
- An allowlisted RegImpact client with deadlines, bounded retries, circuit breaking,
  correlation propagation and typed error handling.
- Conversation state, prompt construction, model/tool orchestration, answer
  generation, safe rendering and user experience.
- Claim-to-passage support evaluation, multi-citation assembly, uncertainty/conflict
  handling and refusal when evidence is insufficient.
- Companion-side user/session/query rate limits, abuse detection, cache partitioning
  by organization and version hash, and companion-specific audit/metrics.
- Evaluation datasets and quality/safety tests. The companion must not write results
  back or promote them automatically.

### D. Deferred production and operator decisions

- Final Entra application registrations, URI values, approved delegated scope names,
  admin-consent owners, client IDs, and authorized `azp` allowlist.
- Whether review and workflow status have an approved first-release purpose and data
  classification; the default is disabled.
- Whether any future app-only business case exists; the current decision is none.
- Private-network placement, ingress/egress, DNS, firewall and workload identity for
  the separate companion deployment.
- Production embedding provider/model, index backfill/readiness policy, data residency
  and model/vendor approvals.
- Per-client/organization/capability quotas, timeouts, SLOs, deprecation window,
  retention, audit sink and security-alert ownership.
- Source URI exposure policy and whether locators require signed/mediated access rather
  than returning a stored URI.

## Acceptance gates

The separate companion repository must not be connected to RegImpact until all of the
following are objectively complete:

1. Security and API owners approve the exact delegated scope names, empty first-release
   application-role allowlist, registered client IDs and route-to-capability matrix.
2. The implemented endpoint allowlist denies every route not explicitly registered,
   including all writes, admin functions, ingestion, indexing, identity management and
   operational endpoints.
3. Automated authorization tests exercise every intersection element: token audience,
   principal type, scope/role distinction, client grant, active external mapping/user,
   local role, organization and resource ownership. Removing any one element denies.
4. Tenant-isolation tests cover valid and random foreign IDs, filters, list/search
   results, related records, citations, caches, audit records and error equivalence.
5. Citation contract tests prove stable IDs, organization ownership, version/content
   hash matching, source locator resolution and stale/mixed-version rejection. Quality
   evaluation separately proves claim support; retrieval score is never accepted as
   proof.
6. All exposed collection routes enforce deterministic bounded pagination. Search is
   bounded, filtered, rate-limited, index-ready and production-configured.
7. Rate-limit tests prove per-client/organization/capability isolation, search budgets,
   `429`/`Retry-After`, emergency client shutdown and companion retry behavior.
8. Audit verification proves authorized and denied calls are correlated and durable,
   while tokens, assertions, sensitive claims, raw queries, evidence bodies and
   rationales never enter logs, audit events or metric labels.
9. An integration test plan obtains a real non-production OBO token, verifies exact
   audiences and `azp`, exercises the allowlist, and proves browser/companion-audience,
   legacy, app-only and wrong-tenant tokens fail. CI continues to use deterministic
   local keys/mocks without weakening production validation.
10. Platform and security owners approve the companion deployment/private-network
    design, distinct identity, secretless or Key Vault-backed credentials, egress
    policy, observability, emergency shutdown and rollback procedure.
11. The OpenAPI subset, error envelope, pagination, retry/deadline and compatibility
    contracts are versioned and pass a generated-client smoke test.
12. Review/workflow endpoints remain disabled unless the governance owner records an
    explicit approval and their additional tests/audits pass.

Until these gates pass, this ADR authorizes design and implementation work only; it
does not authorize production companion access.
