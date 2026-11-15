# ADR: Companion authentication and authorization contract

Status: proposed

Date: 2026-11-14

Decision owners: RegImpact application, platform security, and companion teams

## Context

This ADR defines the authentication and authorization boundary required before a separate RegImpact companion may integrate with RegImpact. It is based on the verified findings in `docs/companion-phase-0-audit.md`. It defines a target contract; it does not claim that the contract is implemented.

Terminology in this ADR:

- **Current** identifies behavior verified in this repository.
- **Decision** identifies the target contract adopted by this ADR.
- **Optional** identifies non-blocking hardening that may follow the first integration.

No browser token may be passed through the companion to RegImpact. The companion receives and requests tokens only for its own server-side audiences and operations.

## Current verified behavior

### Identity and tokens

- RegImpact currently issues a custom HS256 JWT after credential login. It contains `sub`, `org`, `role`, `iat`, `exp`, `iss="regimpact-api"`, and `aud="regimpact-web"`; the configured default lifetime is 30 minutes (`apps/api/src/regimpact/auth.py::issue_access_token`; `apps/api/src/regimpact/config.py::Settings.access_token_minutes`).
- The API accepts only the exact HS256 header, fixed issuer/audience, and a non-expired token. It then loads an active user by `(user_id, organization_id)` and requires the token role to match the current database role (`apps/api/src/regimpact/auth.py::_decode_access_token`, `get_current_user`; `apps/api/tests/test_auth.py::test_signed_token_resolves_database_identity_and_rejects_tampering`).
- Roles are `admin`, `analyst`, and `viewer`. `Authenticated` admits all three; `ReviewerUser` admits admin/analyst; `AdminUser` admits admin only (`apps/api/src/regimpact/auth.py::VALID_ROLES`, `require_roles`, `Authenticated`, `ReviewerUser`, `AdminUser`).
- Credential login searches by lower-cased email without an organization discriminator, although database uniqueness is `(organization_id, email)`. The same email in multiple organizations is therefore ambiguous (`apps/api/src/regimpact/auth_api.py::_login`; `apps/api/src/regimpact/db_models.py::UserRecord`; `apps/api/migrations/versions/20260901_0009_auth_rbac.py::upgrade`).
- `legacy_headers` creates a compatibility admin identity for tests. Production configuration rejects it, and production also rejects demo mode (`apps/api/src/regimpact/auth.py::get_current_user`; `apps/api/src/regimpact/config.py::Settings.validate_security_settings`; `apps/api/tests/test_auth.py::test_production_rejects_demo_mode_configuration`).

### Browser and console

- The Next.js login route calls `POST /api/v1/auth/login` and stores the returned access token in an HTTP-only, SameSite=Lax cookie. `Secure` is controlled by `REGIMPACT_COOKIE_SECURE` and enabled in Azure (`apps/web/app/api/auth/login/route.ts::POST`; `apps/web/app/api/auth/demo-login/route.ts::POST`; `infra/main.bicep::web`).
- Server-side console code reads the cookie and forwards the same bearer token to FastAPI. The page proxy checks only for cookie presence; FastAPI performs token validation (`apps/web/lib/api.ts::apiGet`; `apps/web/app/api/auth/me/route.ts::GET`; `apps/web/proxy.ts::proxy`).
- Logout clears the cookie but there is no central session revocation, refresh-token service, MFA, or external OIDC integration (`apps/web/app/api/auth/logout/route.ts::POST`; `docs/authentication-and-rbac.md::Known limits`).

### Tenant, routing, audit, and deployment

- Authenticated routes derive organization and actor from `CurrentUser`; tenant-owned queries then filter by that organization. There is no database row-level security, so HTTP/service authorization is the mandatory tenant boundary (`apps/api/src/regimpact/auth.py::CurrentUser`, `get_current_user`; `apps/api/src/regimpact/db_models.py`; migrations `20260825_0001` through `20260903_0012`).
- Request middleware accepts or creates `X-Request-ID`, propagates W3C `traceparent`, and exposes request, trace, actor, and organization context to structured logs (`apps/api/src/regimpact/main.py::request_context`; `apps/api/src/regimpact/observability.py::request_id_context`, `trace_id_context`, `actor_id_context`, `organization_id_context`; `apps/api/tests/test_observability.py`).
- Durable audit events currently contain organization, actor, event/entity identity, JSON detail, and time. They do not have structured client, scope, request, trace, or token-exchange fields (`apps/api/src/regimpact/db_models.py::AuditEventRecord`; current `AuditEventRecord(` call sites under `apps/api/src/regimpact`).
- Azure exposes the Next.js console publicly and FastAPI only through internal ingress. API, web, worker, dispatcher, scheduler, and migration workloads share one user-assigned managed identity; there is no companion workload or companion client identity (`infra/main.bicep::identity`, `api`, `web`, `worker`, `dispatcherJob`, `schedulerJob`, `migrationJob`).
- Azure stores the current shared JWT secret in Key Vault. Local Compose injects the same application JWT secret into the API and enables local demo login (`infra/main.bicep::jwtSecretResource`, `commonSecrets`; `docker-compose.yml::api`, `web`).

## Decision

RegImpact will use three distinct resource audiences and two explicit authorization modes:

1. a console session audience for browser-to-console authentication;
2. a companion audience for console/API-to-companion calls;
3. a RegImpact API audience for console/companion-to-RegImpact calls;
4. user-delegated tokens when a human's identity or authority matters; and
5. narrowly scoped service tokens only for approved non-human background reads.

Every inter-service token is short-lived, audience-specific, asymmetrically signed by an approved issuer, and validated by the resource server. Effective permission is the intersection of token scope, client grant, current human role or service grant, tenant membership, resource ownership, and route policy. Any missing or inconsistent element denies the request.

Phase 1 companion integration is read-only. Companion-initiated writes remain denied until the additional gates in this ADR are met.

## Authentication flows

### 1. Browser to RegImpact console

#### Current

The browser submits credentials to a Next.js server route. Next.js calls the RegImpact login API and stores the returned `aud=regimpact-web` JWT in an HTTP-only cookie, then forwards it to FastAPI on later server requests (`apps/web/app/api/auth/login/route.ts::POST`; `apps/web/lib/api.ts::apiGet`; `apps/api/src/regimpact/auth.py::issue_access_token`).

#### Decision

- The browser authenticates only to the RegImpact console using an approved workforce identity provider and authorization-code flow with PKCE.
- The browser receives only an opaque console session identifier in an HTTP-only, `Secure`, SameSite cookie. Access and refresh credentials remain server-side and must not be placed in browser storage, JavaScript-readable cookies, URLs, logs, or page data.
- The console session audience is `regimpact-web` during migration to preserve the existing resource name. That token is valid only at the console/BFF, not at FastAPI or the companion.
- Cookie-authenticated state-changing console routes require CSRF protection in addition to SameSite behavior.
- The console resolves the external immutable subject to a RegImpact user and explicit organization membership. Email is display/contact data, not an identity key.

### 2. RegImpact console or API to companion

#### Console to companion, user-delegated

- The console server exchanges its authenticated user session for a short-lived token with `aud=regimpact-companion` and `azp`/client identity `regimpact-console`.
- The token carries the immutable user subject, RegImpact user ID, organization ID, delegated scopes, authentication time/assurance where available, and a delegation/actor claim that identifies the console client.
- The companion accepts the token only from the approved issuer, for its exact audience, and from an allowlisted console client. It must not forward that token to RegImpact.

#### RegImpact API to companion, service-to-service

- If a future RegImpact API workflow must call the companion without an interactive user, RegImpact uses its own workload identity to request `aud=regimpact-companion` with an allowlisted service scope.
- The token identifies `regimpact-api` as a service principal and carries no fabricated human `sub`, role, or approval authority.
- API-to-companion service calls are denied until a concrete operation is approved and included in both services' client/scope policies. No such operation is required for Phase 1.

### 3. Companion to RegImpact API

#### User-delegated

- For a call made on behalf of a signed-in user, the companion server exchanges the validated companion token for a new token with `aud=regimpact-api` and authorized client `regimpact-companion`.
- The exchange may only reduce scopes. The issued scope set is the intersection of the requested operation, the companion client's grant, the user's current RegImpact role, the user's current tenant membership, and environment policy.
- FastAPI resolves the delegated subject to an active RegImpact user and rechecks role and tenant membership on every request, preserving the current database recheck behavior of `get_current_user` (`apps/api/src/regimpact/auth.py::get_current_user`).

#### Service identity

- Approved non-interactive work uses the companion workload identity to obtain `aud=regimpact-api` through client credentials or platform workload federation.
- Each service principal has explicit tenant grants and scope allowlists. A caller-supplied organization claim alone never grants tenant access.
- Phase 1 service identities may receive read scopes only. They may not create workflows, suggest or decide mappings, approve/reject workflows, manage controls/sources/users, run models, index data, replay jobs, or impersonate a person.
- Service and delegated tokens are distinguishable by principal type and claims; a service token cannot satisfy a route that requires a human subject.

## Token audiences and prohibition on passthrough

| Resource | Required audience | Authorized callers | Rejected tokens |
| --- | --- | --- | --- |
| RegImpact console/BFF | `regimpact-web` | Browser session established through the approved identity flow | API or companion audience tokens |
| Companion | `regimpact-companion` | `regimpact-console`; later, explicitly allowlisted RegImpact service clients | `regimpact-web`, `regimpact-api`, arbitrary client tokens |
| RegImpact API | `regimpact-api` | `regimpact-console` and `regimpact-companion` through approved exchange; allowlisted workload identities | Current `aud=regimpact-web` browser token after migration, companion-audience tokens, unknown clients |

Browser-token passthrough is prohibited because it:

- violates the token's intended resource audience;
- exposes a bearer credential to an additional service;
- prevents least-privilege scope reduction at each hop;
- obscures the authorized client and delegation chain;
- creates a confused-deputy path in which the companion can replay console authority; and
- makes revocation, audit attribution, and service isolation materially weaker.

The current console-to-FastAPI forwarding of `aud=regimpact-web` is a verified legacy behavior, not the target companion contract (`apps/api/src/regimpact/auth.py::issue_access_token`, `_decode_access_token`; `apps/web/lib/api.ts::apiGet`). It must be replaced with an API-audience exchange before companion integration.

## Scopes and permission mapping

### Scope rules

- Scope never replaces RegImpact RBAC. Both scope and the existing role check must authorize the operation.
- A delegated token cannot exceed the user's current role. A client cannot request a scope outside its registered grant.
- A service token has no RegImpact user role. It is evaluated against a separate service grant and cannot satisfy `ReviewerUser` or `AdminUser` routes.
- Phase 1 grants only the read scopes marked as service-eligible below. Write scopes are reserved names, denied until their acceptance gates pass.
- Administrative/model scopes are intentionally not companion scopes: user management, organization provisioning, regulation/source/ingestion/control mutation, ingestion replay, obligation extraction, clause classification, search indexing, queue/operations access, and workflow approval remain outside the companion boundary (`apps/api/src/regimpact/api.py`; `controls_api.py`; `auth_api.py`; `operations_api.py`).

### Companion permission matrix

| Companion operation | Proposed scope | Current routes / permission | Principal allowed | Resource boundary | Required durable audit |
| --- | --- | --- | --- | --- | --- |
| List regulations and versions | `regulations:read` | `GET /api/v1/regulations`, `GET /api/v1/regulations/{id}/versions`; `Authenticated` | Delegated viewer+, service with tenant grant | Authenticated organization; regulation must be owned | access outcome, organization, client, principal, route, regulation IDs, correlation |
| Read changes and citation detail | `changes:read` | `GET /api/v1/changes`, `GET /api/v1/changes/{id}`; `Authenticated` | Delegated viewer+, service with tenant grant | Authenticated organization; foreign change remains not found | same, plus change/version IDs |
| Search regulatory evidence | `evidence:read` | `GET /api/v1/search`; `Authenticated` | Delegated viewer+, service with tenant grant | Organization and embedding-model filters in retrieval | same, plus query hash, result IDs/count; never raw query in audit by default |
| Read obligations/classifications/calibration | `evidence:read` | `GET /api/v1/obligations`, `GET /api/v1/clause-classifications`; `Authenticated`; calibration route is currently public | Delegated viewer+, service with tenant grant | Organization for evidence; calibration contains no tenant data | evidence IDs/model ID/result count; public calibration access need not be tenant-audited |
| Read controls and mapping candidates | `controls:read` | `GET /api/v1/controls`, `GET /api/v1/control-mappings`; `Authenticated` | Delegated viewer+, service with tenant grant | Authenticated organization | control/obligation/mapping IDs and correlation |
| Read review queue/detail | `reviews:read` | `GET /api/v1/review-queue`, `GET /api/v1/review-queue/{id}`; `Authenticated` | Delegated viewer+; service only if separately approved | Authenticated organization; obligation must be owned | filters hash, returned obligation IDs/count, principal/client |
| Read workflow state | `workflows:read` | `GET /api/v1/agent-workflows`, `GET /api/v1/agent-workflows/{id}`; `Authenticated` | Delegated viewer+; service only if separately approved | Authenticated organization; run must be owned | workflow IDs/statuses and correlation |
| Request mapping suggestions | `mappings:suggest` | `POST /api/v1/obligations/{id}/control-mappings/suggest`; `ReviewerUser` | Delegated analyst/admin only; no Phase 1 service | Owned obligation and controls | existing domain event plus client, delegated user, scope, correlation, input/result IDs |
| Start controlled workflow | `workflows:create` | `POST /api/v1/agent-workflows`; `ReviewerUser` | Delegated analyst/admin only; no service | Owned obligation; idempotency key and policy gates | existing workflow event plus client, delegated user, scope, correlation, request hash |
| Record mapping decision | `mapping-decisions:write` | `POST /api/v1/obligations/{id}/mapping-decisions`; `ReviewerUser` | Delegated analyst/admin only; no service | Owned obligation/mapping; revision and idempotency checks | existing decision event plus full delegation/correlation/idempotency context |
| Approve/reject workflow | no companion scope in initial contract | `POST /api/v1/agent-workflows/{id}/decisions`; `AdminUser`, high-risk separation of duties | **Prohibited through companion until a later ADR** | Owned run; different approver for high risk | existing decision event is insufficient without later approval-specific governance |
| Administrative/model/operations writes | no companion scope | Admin routes for users, sources, ingestion, controls, extraction, classification, indexing, replay, operations | **Prohibited** | Not exposed to companion | denied-call security audit when attempted |

The existing route dependencies supporting this mapping are declared in `apps/api/src/regimpact/api.py`, `controls_api.py`, `review_api.py`, `agent_api.py`, `auth_api.py`, and `operations_api.py`. Existing denial and tenant tests include `apps/api/tests/test_auth.py::test_viewer_cannot_create_controls`, `test_operational_snapshot_is_admin_only`, `apps/api/tests/test_review_workflow.py::test_tenant_cannot_read_or_decide_another_tenants_work`, and `apps/api/tests/test_agent_workflow.py::test_tenant_boundary_hides_foreign_obligation`.

## Delegated exchange versus service identity

| Situation | Required mode | Reason |
| --- | --- | --- |
| Interactive evidence search or read in a user's companion session | User-delegated exchange | Preserves user, tenant, role, client, and least-privilege scope |
| Drafting a proposed analyst action | User-delegated exchange | Draft must remain attributable to the human session even before an authoritative write |
| Mapping suggestion, workflow creation, or future mapping decision | User-delegated exchange only | Existing routes require reviewer authority and write actor/rationale/audit state |
| Workflow approval/rejection | Not allowed in the initial companion contract | Existing admin and separation-of-duties rules are a human authority boundary (`agent_workflow.py::decide_workflow`) |
| Scheduled cache warming, evaluation, or prefetch | Service identity, only after explicit approval | No human is acting; grant must be read-only, tenant-specific, bounded, and revocable |
| Operational administration, model execution, ingestion, source/control/user management | Neither mode through companion | Outside the companion trust boundary |

A service identity must never be converted into a human identity, assigned `admin`, or allowed to supply an arbitrary actor/user header. A delegated exchange must preserve the original human subject and identify each acting client; the companion may not replace the subject with its own service principal.

## Identity and correlation propagation

### Required token identity

User-delegated API tokens must carry or resolve:

- immutable issuer and subject;
- exact audience;
- authorized client (`azp` or equivalent);
- delegation/actor chain identifying console and companion where applicable;
- RegImpact organization membership or an opaque membership identifier resolved server-side;
- RegImpact user identifier;
- granted scopes;
- issued-at, not-before, expiry, unique token ID, and authentication time/assurance where available;
- principal type `user`.

Service tokens must carry or resolve:

- issuer, exact audience, client/service principal ID, scopes, issued-at/not-before/expiry, unique token ID;
- principal type `service`; and
- server-side tenant grants. A token-provided organization is advisory until matched to that grant.

### Required request context

- The originating service creates or forwards a valid `traceparent` and a bounded `X-Request-ID`.
- Each service creates its own span while preserving the trace ID. A caller cannot set actor or organization through headers.
- FastAPI resolves actor and organization from validated identity and current grants, then records them in logging and audit context. This extends the existing context behavior in `apps/api/src/regimpact/main.py::request_context` and `apps/api/src/regimpact/auth.py::get_current_user`.
- Companion requests include a stable operation name and idempotency key for every permitted mutation. Correlation identifiers are not authorization inputs.
- Raw access tokens, authorization headers, cookies, prompts, regulatory text, and raw search queries are excluded from authentication logs and durable audit details.

## Token lifecycle and secret handling

### Lifetime

- Console session: maximum 30-minute idle period and 8-hour absolute period, subject to stricter workforce policy and reauthentication for sensitive actions.
- Console, companion, and API access tokens: `exp` and `nbf` are mandatory and `exp - iat` must not exceed the resource's configured maximum. The RegImpact validator defaults to an Entra-compatible 90 minutes; a 10-minute maximum is enabled only after the operator explicitly provisions and verifies the corresponding identity-platform policy.
- Service access tokens follow the same configured maximum; shorter explicitly provisioned platform policies are preferred.
- Exchanged tokens may not outlive the source user session or source token and may only reduce privilege.
- No long-lived bearer token or refresh token is stored in the browser. Server-side refresh capability, if used, follows the identity provider's rotation and replay-detection controls.

### Signing, rotation, and revocation

- Staging and production use an approved external issuer and asymmetric signatures with pinned issuer/audience/algorithm policy and cached JWKS key rotation. The current shared HS256 application secret is not used for companion trust (`auth.py::_decode_access_token`; `infra/main.bicep::jwtSecretResource`).
- Signing keys rotate under identity-platform policy with overlap sufficient for in-flight short-lived tokens. Unknown, missing, retired, or algorithm-mismatched key IDs fail closed.
- Disabling a RegImpact user, changing a role, removing tenant membership, disabling a companion client, or removing a service tenant grant takes effect on the next request through a current-state lookup. Maximum token lifetime bounds residual exposure.
- An incident response control must revoke the companion client/workload identity and block its token IDs or signing keys when immediate invalidation is required.
- Token exchange never returns a refresh token to the companion unless a later security review explicitly approves offline access. Phase 1 has no offline user delegation.

### Secrets

- Prefer workload federation/managed identity; do not provision client secrets where the platform supports federation.
- If a secret is unavoidable in local/CI integration testing, it is unique to that environment, stored in the platform secret store, never committed, never shared between console/API/companion, and rotated after exposure or on a defined schedule.
- Neither repository may share the current `REGIMPACT_JWT_SECRET`, database URL, Redis URL, Key Vault access, object-storage credential, or managed identity (`infra/main.bicep::commonSecrets`, `identity`; `docker-compose.yml`).
- Tokens and secrets are redacted from application, proxy, CI, telemetry, and error output.

## Deny by default and privilege-escalation controls

RegImpact and the companion deny a request unless all applicable checks pass:

1. issuer, signature, allowed asymmetric algorithm, key ID, audience, time claims, and token type;
2. authorized client and principal type;
3. requested route's explicit scope;
4. client registration/grant for that scope and environment;
5. current user active state, tenant membership, and existing RegImpact role, or current service tenant grant;
6. route RBAC (`Authenticated`, `ReviewerUser`, or `AdminUser`) for user tokens;
7. tenant ownership of every referenced resource; and
8. route-specific revision, idempotency, policy, and separation-of-duties rules.

Additional rules:

- Unknown clients, scopes, audiences, principal types, claims, or token exchange purposes do not receive fallback access.
- Scope-to-route mapping is allowlist-based. A broad scope does not imply narrower or administrative scopes unless explicitly registered.
- Role claims are not authoritative by themselves; FastAPI rechecks current database authorization.
- A service principal cannot satisfy a human-role dependency and cannot use `X-Actor-ID` or `X-Organization-ID` to select identity. `legacy_headers` remains test-only and is forbidden outside local/CI compatibility tests (`auth.py::get_current_user`; `config.py::validate_security_settings`).
- The companion cannot request scopes it did not receive, switch organizations within a token, or use resource identifiers from another tenant. Foreign tenant resources return the same not-found behavior as current APIs where appropriate.
- The companion is never granted organization/user administration, source/ingestion/control mutation, model execution, search indexing, replay, operations, or workflow approval through implied `admin` access.
- Rate limits apply per client, tenant, subject/service principal, and sensitive route. Token exchange and authentication endpoints receive stricter limits and generic failure responses.

## Required audit events

Every companion path must produce security telemetry; authorized companion API calls must also produce durable tenant audit records. Existing domain events remain authoritative for writes but require added companion context (`apps/api/src/regimpact/db_models.py::AuditEventRecord`; `apps/api/src/regimpact/review_workflow.py::decide_mapping`; `apps/api/src/regimpact/agent_workflow.py::create_workflow`, `decide_workflow`).

### Event types

| Event | When | Required outcome |
| --- | --- | --- |
| `companion.token_exchange_succeeded` | A delegated or service token is issued | issuer, target audience, client, principal type, subject/service ID, organization grant, granted scopes, token ID hash, request/trace IDs |
| `companion.token_exchange_denied` | Exchange fails policy | client when known, requested audience/scopes, denial code, request/trace IDs; no raw token or credentials |
| `companion.api_call_authorized` | RegImpact accepts a companion call | organization, actor/service ID, client, principal type, delegation chain, scopes, method, route template, bounded resource IDs, outcome/status, request/trace IDs |
| `companion.api_call_denied` | Authentication, scope, role, tenant, ownership, or policy check denies | known client/principal/organization, denial category, route template, request/trace IDs; security log if tenant cannot be safely resolved |
| Existing domain event with companion context | A permitted companion write creates a mapping suggestion, workflow, or decision | existing entity/revision/rationale behavior plus client, delegated subject, scope, request/trace IDs, idempotency key and canonical request hash |
| `companion.credential_revoked` | Client, workload identity, tenant grant, key, or token is revoked | actor authorizing revocation, target, reason, effective time, correlation |

For evidence search, audit stores a normalized query hash, filters hash, returned evidence IDs/count, and model/index lineage where relevant; raw query or evidence text is not stored by default. Audit retention, export access, and high-volume read aggregation remain governance decisions, but dropping client/tenant/principal attribution is not permitted.

## Environment contract

### Local development

- Local Compose may retain demo users and `REGIMPACT_COOKIE_SECURE=false` only on loopback/developer networks (`docker-compose.yml::api`, `web`; `auth_api.py::demo_login`).
- Companion integration uses a dedicated local issuer/emulator or checked-in public test keys with non-secret private material generated at runtime. Test tokens use local-only issuer and audience values that production rejects.
- `legacy_headers` may remain for existing unit tests but is not accepted as a companion authentication path.
- Local console, companion, and API use distinct client identities and secrets/keys even when co-located.

### CI

- CI generates ephemeral signing keys or starts an identity emulator; no staging/production signing credential is available.
- Tests exercise all three audiences, both principal types, scope/RBAC intersection, tenant boundaries, token exchange, revocation behavior, correlation, and audit completeness.
- CI must fail on committed secrets, tokens, private keys, or environment files. The existing workflow already rejects common secret patterns and `.env` (`.github/workflows/quality.yml::infrastructure-validation`).

### Staging

- Staging uses the real approved identity platform, separate app registrations/workload identities, asymmetric keys, exact staging audiences, internal API networking, and production-shaped scope policies.
- Demo login and legacy headers are disabled. The existing deployment already keeps demo mode unset and API ingress internal (`infra/main.bicep::commonEnv`, `api`; `docs/azure-deployment.md::Deployed topology`).
- Companion credentials, tenant grants, exchange failures, audit events, and revocation are tested with synthetic tenants. Staging remains ephemeral unless explicitly retained (`.github/workflows/deploy-azure.yml`; `docs/azure-deployment.md::Cost control`).

### Production

- Production requires enterprise workforce identity, workload federation, private connectivity, approved tenant/client provisioning, centralized revocation, key rotation, rate limits, alerting, audit retention/export, incident runbooks, and independent security approval.
- No local issuer, demo account, legacy header, shared HS256 secret, public FastAPI exposure, or unregistered companion client is allowed.
- This repository does not currently approve production deployment; private networking and workforce identity remain explicit boundaries (`docs/azure-deployment.md::Known production boundary`; `docs/release-audit-v0.5.md`).

## Required RegImpact implementation changes

This section defines work required by the contract; no work is implemented by this ADR.

### Blocking before any companion call

1. Replace the API's fixed `aud=regimpact-web` HS256 validation path with approved issuer/JWKS validation for exact `aud=regimpact-api`, while retaining a time-bounded migration plan for the console (`apps/api/src/regimpact/auth.py::issue_access_token`, `_decode_access_token`).
2. Change the console BFF so it does not forward the console/browser token to FastAPI. It must obtain API-audience tokens server-side and companion-audience tokens only when calling the companion (`apps/web/lib/api.ts::apiGet`; Next.js API proxy routes under `apps/web/app/api`).
3. Add a principal model that distinguishes delegated users from services and records authorized client/delegation chain. User calls must continue to recheck active user, tenant, and role (`apps/api/src/regimpact/auth.py::CurrentUser`, `get_current_user`).
4. Add explicit scope dependencies and a reviewed route-to-scope allowlist. Effective authorization must intersect scope, client grant, current RBAC/service grant, tenant, and resource ownership.
5. Add companion client registration and tenant-scoped service grants with revocation. Resolve external immutable subjects; do not use email as the identity key (`apps/api/src/regimpact/auth_api.py::_login`; `apps/api/src/regimpact/db_models.py::UserRecord`).
6. Define and deploy the token-exchange/identity-platform configuration for `regimpact-web`, `regimpact-companion`, and `regimpact-api`, using separate clients and asymmetric keys.
7. Give the companion a distinct workload identity and private network path to internal FastAPI. Do not share the existing RegImpact managed identity or secrets (`infra/main.bicep::identity`, `api`, `commonSecrets`).
8. Add per-client/tenant/principal rate limits and stable authentication/authorization denial codes. Current FastAPI errors distinguish `unauthenticated` and `forbidden` but have no scope/client-specific catalogue (`apps/api/src/regimpact/main.py::http_error`).
9. Persist companion client, principal type, delegated subject, scopes, request/trace IDs, and idempotency/request hashes in durable audit events; add an authorized audit export/read path or reconciliation mechanism (`apps/api/src/regimpact/db_models.py::AuditEventRecord`).
10. Implement the security tests and gates below. Phase 1 enables read scopes only.

### Blocking before companion writes

1. Complete a separate approval for each write scope and route; do not infer write authority from read scopes or `admin`.
2. Require delegated human tokens for mapping suggestions, workflow creation, and any mapping decision. Service tokens remain denied.
3. Correct workflow-create idempotency so reuse for a different obligation or request hash is rejected, not returned as the earlier run (`apps/api/src/regimpact/agent_workflow.py::create_workflow`).
4. Bind audit, correlation, canonical request hash, idempotency key, revision, and delegated human to the authoritative domain event.
5. Validate confirmation UX, stale-revision handling, replay/race behavior, separation of duties, and incident rollback.
6. Workflow approval remains prohibited until a later ADR explicitly accepts companion-mediated approvals.

### Optional hardening

- Sender-constrained tokens through mTLS or proof-of-possession where platform support and threat analysis justify them.
- Token introspection or a distributed token-ID denylist for immediate revocation beyond short lifetime and current-state checks.
- SCIM or automated workforce/user lifecycle provisioning.
- Fine-grained resource attributes beyond tenant and current roles.
- Dedicated structured audit columns/indexes instead of placing all new context in `detail_json`.
- Step-up authentication for future high-risk writes.
- A companion-specific API facade that exposes fewer routes than the shared `/api/v1` routers.

## Security acceptance criteria and required tests

Companion integration is denied until all applicable criteria pass in CI and staging.

### Token validation and audience isolation

- Valid token for each resource audience succeeds only at that resource.
- `regimpact-web` token is rejected by companion and API; `regimpact-companion` token is rejected by API; `regimpact-api` token is rejected by console and companion.
- Wrong issuer, signature, algorithm, key ID, token type, client, expiry, not-before, issued-at, token ID, or malformed claims fail closed without leaking validation detail.
- Algorithm confusion, unsigned tokens, stale/retired keys, duplicate/ambiguous claims, and key-fetch failure are rejected.
- JWKS rotation accepts the overlap window and rejects retired keys after policy expiry.

### Exchange and principal controls

- Only registered console/companion clients may exchange tokens, only for allowed audiences, and only for a subset of granted scopes.
- Exchange preserves immutable user subject, authorized client/delegation chain, tenant membership, and authentication context.
- Cross-tenant exchange, organization switching, scope escalation, client substitution, service-to-user conversion, and arbitrary actor headers are rejected.
- Service tokens cannot satisfy `ReviewerUser` or `AdminUser`, cannot call write/admin routes, and cannot impersonate a user.
- Disabled users, changed roles, removed memberships, disabled clients, and revoked service tenant grants are denied on the next call.

### Scope, RBAC, and tenant isolation

- Every matrix route has allow tests for its intended role/principal and deny tests for missing/wrong scope, wrong role, wrong principal type, wrong client grant, and foreign tenant resource.
- Viewer cannot obtain reviewer/admin effects; analyst cannot obtain admin effects; no companion principal can obtain organization/user/source/ingestion/control/model/index/replay/operations/approval effects.
- Foreign resource identifiers return the approved non-disclosing response and create no cross-tenant side effect.
- Unknown scopes and routes are denied; absence of a scope mapping cannot fall back to role-only authorization.
- Existing tenant/RBAC tests continue to pass, including `tests/test_auth.py`, `tests/test_read_api.py`, `tests/test_retrieval.py`, `tests/test_review_workflow.py`, and `tests/test_agent_workflow.py`.

### Browser, secrets, correlation, and audit

- Browser tests prove no API/companion access token appears in JavaScript storage, page content, URL, or readable cookie; session cookies are HTTP-only, Secure outside local, SameSite, bounded, and CSRF-protected.
- Logs, traces, errors, CI output, and audit events contain no raw token, credential, cookie, authorization header, refresh token, prompt, or evidence text.
- `traceparent` and bounded `X-Request-ID` correlate console -> companion -> API while each service creates its own span.
- Authorized and denied companion calls create required security/audit events with client, principal, tenant when known, scope, route, outcome, and correlation.
- Permitted writes create exactly one authoritative domain event on idempotent retry and preserve delegated subject, client, revision, and request hash.

### Lifecycle, resilience, and environment

- Token expiration, key rotation, user/client/grant revocation, issuer/JWKS outage, clock skew, replay, rate limit, and dependency failure have documented fail-closed outcomes.
- Authentication/token endpoints enforce rate limits and generic errors; API callers receive stable `401`, `403`, and `429` contracts and do not retry permanent denials.
- Local/CI identities and issuers are rejected by staging/production. Demo login and `legacy_headers` are unavailable in staging/production.
- Staging proves private connectivity from a distinct companion identity without shared database, Redis, storage, Key Vault, JWT secret, or RegImpact managed identity.
- An independent threat model and security review cover confused deputy, token theft/replay, tenant confusion, privilege escalation, prompt-driven tool misuse, and audit tampering.

## Consequences

### Positive

- Resource audiences and per-hop exchange limit token replay and make the acting client visible.
- Existing RegImpact RBAC, tenant filters, revision checks, and human approval boundaries remain authoritative.
- Read-only service automation is possible without inventing a fake user or granting admin.
- Short lifetimes, current-state checks, distinct identities, and durable audit improve revocation and incident response.

### Costs and tradeoffs

- The console's current simple token forwarding must change before companion integration.
- RegImpact needs an external identity/token-exchange integration, client/service grant model, route scopes, richer audit context, rate limits, and additional tests.
- Separate clients, keys, identities, and private network paths add platform and operational ownership.
- Auditing all companion reads increases event volume and requires an explicit retention/export design.

## Rejected alternatives

- **Forward the browser token through the companion.** Rejected because the audience is wrong and it defeats least privilege, client attribution, and isolation.
- **Share the RegImpact HS256 secret with the companion.** Rejected because either service could mint the other's tokens and rotation/revocation would be coupled.
- **Give the companion an admin user.** Rejected because a service is not a human, admin includes unrelated capabilities, and approval separation would be bypassed.
- **Trust organization or actor headers.** Rejected because current production identity derives both from validated credentials; header identity exists only for test compatibility (`apps/api/src/regimpact/auth.py::get_current_user`).
- **Give the companion direct database, Redis, object-storage, or Key Vault access.** Rejected because the API/service layer is the tenant authorization boundary and these stores have no companion scope contract.
- **Use one multi-audience bearer token for every hop.** Rejected because compromise of any participant would expose every resource and eliminate per-hop scope reduction.

## Unresolved decisions

The following choices require platform/security ownership before implementation but do not change the deny-by-default principles in this ADR:

1. Approved workforce identity provider and token-exchange mechanism, such as platform on-behalf-of versus a dedicated standards-based security token service.
2. Exact external claim names and mapping for RegImpact organization membership, authorized client, delegation chain, authentication assurance, and principal type.
3. Storage and administration model for companion client registrations and service-to-tenant grants.
4. Private networking/DNS placement when the companion is deployed from a separate repository.
5. Audit retention, export destination, read-event aggregation, and whether new context needs dedicated indexed columns rather than `detail_json`.
6. Emergency token-ID revocation implementation and acceptable issuer/JWKS outage cache window.
7. Whether `reviews:read` and `workflows:read` are available to service identities in Phase 1 or delegated users only.
8. Whether future mapping decisions may be submitted through the companion; workflow approval remains out of scope unless a later ADR supersedes this decision.

## Compliance with the Phase 0 boundary

This decision preserves the ownership boundary in `docs/companion-phase-0-audit.md`: RegImpact remains authoritative for tenants, roles, evidence, controls, workflows, human decisions, and audit; the companion owns conversational orchestration and claim-support presentation. It creates no companion repository and authorizes no code, migration, API, or infrastructure change by itself.
