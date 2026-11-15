# ADR: Production identity provider and companion token exchange

Status: accepted for implementation

Date: 2026-11-14

Decision owners: RegImpact application, companion, platform, and security teams

Related decisions:

- `docs/companion-phase-0-audit.md`
- `docs/adr/companion-authentication-contract.md`

Reading convention: **Current behavior** statements are verified against the repository and cite their evidence. **Selected decision** statements are normative architecture. **Future implementation** statements describe required work and do not imply that code or infrastructure exists today.

## Decision summary

RegImpact will use **Microsoft Entra ID Workforce in one operator-controlled directory** as the production identity provider. The first production release is single-directory: directory members and explicitly invited B2B guests may sign in, but arbitrary external Entra tenants and personal Microsoft accounts are not accepted.

The selected delegated mechanism is **Microsoft Entra OAuth 2.0 On-Behalf-Of (OBO)**:

- the Next.js console is a confidential web client using authorization code with PKCE and OpenID Connect;
- the console calls the companion with a companion-audience delegated access token kept server-side;
- the companion validates that token and uses OBO to obtain a new RegImpact-API-audience token for the minimum downstream delegated scopes; and
- the console obtains a separate RegImpact-API-audience token when it calls FastAPI directly.

Production app-only calls use a distinct user-assigned managed identity and Entra application roles. They never use OBO, never contain a human identity, and cannot perform human decisions. No browser, console, companion, or API token is forwarded to a resource for which it was not issued.

For Entra v2 access tokens, the accepted `aud` is the exact application client-ID GUID of the receiving API. Application ID URIs are used when requesting scopes, but are not treated as interchangeable audience strings. Microsoft documents that v2 access-token audiences are API client IDs and that an API must reject tokens for other audiences ([claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation), [access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens)).

## Current behavior and verified constraints

The current implementation cannot safely authenticate a separate companion:

- `issue_access_token` creates application-issued HS256 tokens with `iss="regimpact-api"` and `aud="regimpact-web"`; `_decode_access_token` accepts only that issuer/audience and a shared `REGIMPACT_JWT_SECRET` (`apps/api/src/regimpact/auth.py::issue_access_token`, `_decode_access_token`; `apps/api/src/regimpact/config.py::Settings.jwt_secret`).
- The console stores that token in an HTTP-only cookie and forwards it unchanged to FastAPI (`apps/web/app/api/auth/login/route.ts::POST`; `apps/web/lib/api.ts::apiGet`; `apps/web/app/api/auth/me/route.ts::GET`).
- The API has roles but no OAuth scopes, authorized-client claim, delegated actor chain, service principal, JWKS validation, central revocation, or external identity mapping (`apps/api/src/regimpact/auth.py::CurrentUser`, `require_roles`; `apps/api/src/regimpact/db_models.py::UserRecord`).
- Azure already uses Container Apps, a user-assigned managed identity, Key Vault, internal FastAPI ingress, and GitHub workload federation, but it defines no identity-provider app registrations or companion workload identity (`infra/main.bicep::identity`, `vault`, `api`, `web`, `commonSecrets`; `.github/workflows/deploy-azure.yml::Authenticate with Azure using OIDC`).
- Production is explicitly blocked on enterprise workforce identity and private networking (`docs/azure-deployment.md::Known production boundary`; `docs/release-audit-v0.5.md`).

## Options considered

| Option | Architectural fit | Security and operations | Decision |
| --- | --- | --- | --- |
| Microsoft Entra ID Workforce, authorization code + OBO + managed identities | Native fit with Azure Container Apps, managed identity, Key Vault, GitHub OIDC, internal APIs, and the stated workforce-identity production boundary | Asymmetric issuer/JWKS, MFA/Conditional Access, OBO, app roles, workload federation, central client/user disablement, and managed credential rotation | **Selected** |
| Retain RegImpact-issued HS256 JWTs and add companion audiences/scopes | Smallest code change and works offline | Shared symmetric signing authority, custom token exchange/revocation/client registry, no workforce MFA/Conditional Access, coupled key rotation, and either service could mint the other's tokens if the secret is shared | Rejected for staging/production; temporary migration compatibility only |
| Self-hosted OIDC/security-token service such as Keycloak | Standards-based and cloud-independent | Adds a new critical stateful identity control plane, signing-key operations, upgrades, HA, backup/recovery, incident response, and federation work that the current Azure architecture does not otherwise need | Rejected for the first production release |
| Third-party workforce IdP such as Okta/Auth0 | Standards-based and potentially suitable when already an enterprise standard | Adds a second vendor/control plane and still needs Azure workload federation plus an OBO-equivalent delegated exchange design; no repository evidence identifies it as the organizational standard | Not selected; reconsider only if the operator mandates it |
| Microsoft Entra External ID or a multitenant Entra app | Appropriate for customer-managed identities in a future SaaS model | Introduces cross-directory consent, issuer allowlists, tenant onboarding, guest/home-tenant OBO concerns, and business tenancy decisions not represented by the current one-organization-per-user schema | Deferred; requires a separate business and tenancy ADR |

### Rationale

Entra is selected because the verified deployment is already Azure-native and the repository explicitly names enterprise workforce identity as a production prerequisite. Entra OBO is the supported delegated flow for a middle-tier API to obtain a downstream API token representing the original user; it uses delegated scopes, not application permissions ([Microsoft Entra OBO flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow)). Managed identities and app-role assignments provide a separate app-only path without stored client secrets or user impersonation ([managed-identity API permissions](https://learn.microsoft.com/en-us/powershell/entra-powershell/grant-api-permissions-managed-identity), [app roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps)).

## Tenant and application-registration model

### Entra directory

- One configured Entra directory tenant ID is accepted in each environment.
- Production and staging use separate app registrations, service principals, redirect URIs, managed identities, consent grants, and configuration. Tokens from one environment are invalid in the other.
- The production issuer is exactly `https://login.microsoftonline.com/{PRODUCTION_ENTRA_TENANT_ID}/v2.0`.
- `common`, `organizations`, `consumers`, personal Microsoft accounts, and unregistered tenant issuers are rejected.
- B2B guests are allowed only after invitation into the configured directory, assignment to the relevant enterprise applications, and an explicit RegImpact user mapping.

The Entra `tid` identifies the workforce directory; it is not the RegImpact organization. `ExternalIdentityRecord` maps the normalized `(provider=entra, tid, oid)` tuple to exactly one existing local user and organization through database-enforced uniqueness and tenant-consistent foreign keys (`apps/api/src/regimpact/db_models.py::ExternalIdentityRecord`, `UserRecord`). Unknown, malformed, ambiguous, disabled, or inactive mappings fail closed and never auto-provision or fall back to direct `oid == UserRecord.id` matching. Email, `preferred_username`, and `name` are display data only. Supporting one Entra identity in multiple RegImpact organizations requires a future membership-model decision and is not inferred from a request header.

### Required app registrations and service principals

| Registration | Type | Purpose | Exposes | Consumes |
| --- | --- | --- | --- | --- |
| `regimpact-console-{env}` | Confidential web client | Browser sign-in, server session, direct FastAPI calls, companion calls | OIDC redirect URI only | RegImpact API delegated scopes; companion `companion:access` |
| `regimpact-companion-{env}` | Web API and confidential middle tier | Accept console user calls; use OBO to RegImpact API | `companion:access`; optional future `Companion.Invoke` app role | RegImpact API delegated scopes |
| `regimpact-api-{env}` | Web API resource | Protect FastAPI | RegImpact delegated scopes and read-only application roles | No downstream permission in Phase 1 |

Public-client flows and implicit grants are disabled. The console uses authorization code with PKCE and server-side code redemption; Microsoft recommends authorization code with PKCE and OIDC for server-based web applications ([authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)).

Each Container App receives its own user-assigned managed identity. The identity is configured as a federated credential for the corresponding confidential app registration and supplies the client assertion used for code redemption or OBO. The federation audience is `api://AzureADTokenExchange`. Microsoft documents this managed-identity-to-app-registration trust for Azure Container Apps ([managed identity federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity), [certificateless authentication](https://learn.microsoft.com/en-us/entra/msidweb/authentication/certificateless)). Client certificates in Key Vault are the approved fallback if the chosen language/library cannot support managed-identity federation; production client secrets are not approved.

## Selected token flows

### Delegated sequence

```mermaid
sequenceDiagram
    actor U as User browser
    participant E as Microsoft Entra ID
    participant C as RegImpact console/BFF
    participant P as Companion API
    participant R as RegImpact FastAPI

    U->>C: Start sign-in
    C->>E: Authorization code + PKCE + OIDC
    E-->>C: Code at registered redirect URI
    C->>E: Redeem code using confidential-client assertion
    E-->>C: ID token + server-side token cache
    C-->>U: Opaque HttpOnly Secure session cookie

    U->>C: Ask companion
    C->>E: Acquire companion:access for this session
    E-->>C: AT-C (aud = companion client ID)
    C->>P: AT-C + traceparent + X-Request-ID
    P->>P: Validate issuer, aud, tid, azp, scp, times, signature
    P->>E: OBO assertion=AT-C, request minimum RegImpact scope
    E-->>P: AT-R (aud = RegImpact API client ID)
    P->>R: AT-R + traceparent + X-Request-ID
    R->>R: Validate token; map tid+oid; intersect scope/RBAC/tenant
    R-->>P: Tenant-scoped result
    P-->>C: Supported companion response
    C-->>U: Render response; no access token reaches browser
```

`AT-C` is presented only to the companion. `AT-R` is presented only to RegImpact FastAPI. The browser receives neither. OBO accepts an access token, not an ID token, as the user assertion and obtains a new downstream token ([OBO guidance](https://learn.microsoft.com/en-us/entra/msal/dotnet/acquiring-tokens/web-apps-apis/on-behalf-of-flow)).

### Browser and console to RegImpact API

1. The browser authenticates at the tenant-specific Entra v2 authorization endpoint using authorization code with PKCE, `state`, and `nonce`.
2. The console redeems the code as a confidential client using its managed-identity federated assertion.
3. The console keeps ID/access/refresh artifacts in its encrypted server-side session/token cache. The browser receives only an opaque HTTP-only, Secure, SameSite session cookie with CSRF protection.
4. When the console calls FastAPI directly, it acquires a separate access token for the exact RegImpact API delegated scopes. The token `aud` is the RegImpact API application client-ID GUID.
5. FastAPI validates the token and maps `(tid, oid)` to the active local user and organization before applying scope, current role, and resource ownership.

This replaces the current behavior in which the console forwards its `aud=regimpact-web` cookie token to FastAPI (`apps/web/lib/api.ts::apiGet`; `apps/api/src/regimpact/auth.py::_decode_access_token`). Browser-token passthrough is prohibited.

### RegImpact console to companion

1. The console acquires `api://{COMPANION_CLIENT_ID}/companion:access` for the signed-in session.
2. It sends that access token server-to-server to the internal companion endpoint with correlation headers.
3. The companion requires the companion client-ID audience, tenant issuer, delegated `companion:access`, user principal, and `azp == REGIMPACT_CONSOLE_CLIENT_ID`.
4. The companion does not reuse or forward the incoming token when calling FastAPI.

FastAPI does not call the companion in Phase 1. A future app-only FastAPI-to-companion call would use the RegImpact API managed identity and a `Companion.Invoke` application role; a future delegated FastAPI-to-companion call would require a separate approved OBO path and is currently denied.

### Companion to RegImpact API through OBO

1. The companion validates `AT-C` before attempting exchange.
2. It sends `AT-C` as the user assertion to the tenant-specific Entra v2 token endpoint using the OBO JWT-bearer grant and proves the companion confidential-client identity through its managed-identity federated assertion.
3. It requests only the downstream RegImpact delegated scopes required for the current operation, not every consented permission and not an application role.
4. Entra returns `AT-R`, whose `aud` is the RegImpact API client-ID GUID, `azp` is the companion client ID, `oid`/`tid` identify the user in the configured directory, and `scp` contains granted delegated scopes.
5. The companion caches the OBO result only within the originating server session and never beyond token expiry. It calls FastAPI with `AT-R`.
6. FastAPI verifies that `azp` is an allowlisted client for each presented scope, resolves the user, and intersects scope with current `viewer`/`analyst`/`admin` RBAC and tenant ownership (`apps/api/src/regimpact/auth.py::require_roles`; authenticated route dependencies in `api.py`, `controls_api.py`, `review_api.py`, and `agent_api.py`).

### App-only service flow

- The companion's distinct user-assigned managed identity obtains a v2 access token for `api://{REGIMPACT_API_CLIENT_ID}/.default`.
- The RegImpact API application exposes application roles; an administrator assigns only approved roles to that managed-identity service principal.
- App-only tokens have the RegImpact API client-ID audience, the configured `tid`, `idtyp=app`, the managed identity/service principal `oid`, `azp` identifying the calling application, and `roles`; they do not contain delegated `scp` or a human actor.
- FastAPI authorizes app-only calls through a separate service-principal path and server-side mapping from service principal to one RegImpact organization. Phase 1 does not allow one service identity to select among multiple organizations.
- No application role permits mapping suggestions, workflow creation, mapping decisions, workflow approvals, user/source/ingestion/control administration, model execution, indexing, replay, or operations access.

Managed identity is selected over a client secret because the current runtime is Azure Container Apps and managed identities remove stored workload credentials. Application roles can be assigned to managed-identity service principals ([managed identity permissions](https://learn.microsoft.com/en-us/powershell/entra-powershell/grant-api-permissions-managed-identity)).

## Token and claim matrix

| Token | Issuer | Exact `aud` | Principal and caller | Required authorization claims | Identity use | Rejected conditions |
| --- | --- | --- | --- | --- | --- | --- |
| Console ID token | tenant-specific Entra v2 issuer | Console client-ID GUID | User authenticating to console | `ver=2.0`, `tid`, `oid`, `sub`, `nonce`, `iat`, `nbf`, `exp`; client/session checks | Establish server-side console session only | Never accepted by companion or FastAPI; never used for OBO |
| Console -> FastAPI access token | same | RegImpact API client-ID GUID | User; `azp=console client ID` | nonempty `scp`, `idtyp=user`, `tid`, `oid`, `sub`, `azp`, `iat`, `nbf`, `exp`, `uti` | Map `(tid,oid)` to local user/org; direct console API calls | Wrong audience/client/tenant, missing scope/user mapping, `roles`-only app token |
| Console -> companion `AT-C` | same | Companion client-ID GUID | User; `azp=console client ID` | `scp` includes `companion:access`; `idtyp=user`, `tid`, `oid`, `sub`, times, `uti` | Authenticate companion request and serve as OBO assertion | Forwarding to FastAPI, app-only token, wrong console client |
| Companion -> FastAPI `AT-R` | same | RegImpact API client-ID GUID | User; `azp=companion client ID` | minimum RegImpact `scp`; `idtyp=user`, `tid`, `oid`, `sub`, times, `uti` | Map user/org; authorize by scope + current RBAC + ownership | Scope escalation, unknown `azp`, service role, different tenant |
| Companion -> FastAPI app token | same | RegImpact API client-ID GUID | Service; companion application/managed identity | `idtyp=app`, `tid`, service `oid`, allowlisted `azp`, approved `roles`, times, `uti`; no delegated `scp` | Resolve one service/organization grant; authorize read-only app role | Any human scope/role, arbitrary organization, write/admin operation |
| Future FastAPI -> companion app token | same | Companion client-ID GUID | Service; RegImpact API managed identity | `idtyp=app`, `tid`, service `oid`, allowlisted `azp`, `roles=[Companion.Invoke]`, times | Approved non-user invocation only | Not enabled in Phase 1; no user impersonation |

`preferred_username`, `email`, and `name` are display-only and never authorization keys. `tid` and `oid` are the stable directory mapping key. `sub` is retained for protocol/session checks but not used as the cross-application database key. `uti` is logged only as a one-way hash for security correlation; no raw token is logged. Microsoft documents `azp` for the v2 client application, `scp` for delegated permissions, `roles` for application permissions, `tid`, `oid`, and `uti` in its [access-token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference).

## Scope and application-role matrix

| Entra permission value | Type | Allowed caller | Existing RegImpact permission intersection | Phase 1 |
| --- | --- | --- | --- | --- |
| `companion:access` | Companion delegated scope | Console confidential client, signed-in user | Companion session policy; does not itself grant FastAPI access | Enabled |
| `regulations:read` | RegImpact delegated scope | Console or companion OBO | `Authenticated`; `GET /api/v1/regulations`, versions | Enabled |
| `changes:read` | RegImpact delegated scope | Console or companion OBO | `Authenticated`; change register/detail | Enabled |
| `evidence:read` | RegImpact delegated scope | Console or companion OBO | `Authenticated`; search, obligations, classifications | Enabled |
| `controls:read` | RegImpact delegated scope | Console or companion OBO | `Authenticated`; controls and mappings | Enabled |
| `reviews:read` | RegImpact delegated scope | Console or companion OBO | `Authenticated`; review queue/detail | Enabled for delegated users |
| `workflows:read` | RegImpact delegated scope | Console or companion OBO | `Authenticated`; workflow list/detail | Enabled for delegated users |
| `mappings:suggest` | RegImpact delegated scope | Companion OBO only after write gate | `ReviewerUser`; mapping suggestion route | Reserved, denied |
| `workflows:create` | RegImpact delegated scope | Companion OBO only after write gate | `ReviewerUser`; start workflow | Reserved, denied |
| `mapping-decisions:write` | RegImpact delegated scope | Companion OBO only after write gate | `ReviewerUser`; mapping decision + revision/idempotency | Reserved, denied |
| `Evidence.Read.All` | RegImpact application role | Companion managed identity | Service grant; regulations, changes, evidence, controls only | Optional, off by default |
| `Reviews.Read.All` | RegImpact application role | Companion managed identity | Service grant; review reads only | Not assigned in Phase 1 |
| `Workflows.Read.All` | RegImpact application role | Companion managed identity | Service grant; workflow reads only | Not assigned in Phase 1 |
| `Companion.Invoke` | Companion application role | RegImpact API managed identity | Companion service policy | Not assigned in Phase 1 |

There is no companion application role for `AdminUser`, workflow approval, user management, organization provisioning, source/ingestion/control mutation, model execution, search indexing, replay, queue health, or operations snapshot. Existing role gates are declared in `apps/api/src/regimpact/auth.py::AdminUser`, `ReviewerUser`; route usage is in `apps/api/src/regimpact/api.py`, `controls_api.py`, `review_api.py`, `agent_api.py`, `auth_api.py`, and `operations_api.py`.

## Token validation and JWKS contract

### Discovery and accepted cryptography

- Use the tenant-specific v2 discovery document: `https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration`.
- Obtain `issuer`, token endpoint, and `jwks_uri` from discovery. Microsoft publishes the tenant JWKS through that metadata ([OIDC discovery](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)).
- Accept only JWT access tokens with `ver=2.0`, `typ=JWT`, and `alg=RS256` whose `kid` resolves to a current key from the configured tenant JWKS.
- Reject `none`, HS256, other symmetric algorithms, tokens with embedded caller-supplied keys, and keys not anchored in the configured discovery document.
- Validate signature before using claims. Then validate exact issuer, exact audience client ID, configured `tid`, authorized `azp`, principal type, scopes or roles, and time claims.

### Key caching and rotation

- Refresh discovery and JWKS in the background at least hourly and honor safe HTTP cache metadata up to a six-hour normal cache period.
- On an unknown `kid`, perform one rate-limited synchronous refresh and retry validation once.
- If refresh fails, a token signed by a still-cached known key may be accepted only until 24 hours after the last successful JWKS refresh and only while all other checks pass.
- Unknown-key tokens always fail closed. After the 24-hour last-known-good ceiling, all new authentication fails closed until trusted metadata is restored.
- Never fetch a JWKS URI from the token itself. Never use `x5u`, `jku`, or an untrusted issuer to select verification keys.

### Time validation

- Permit at most 120 seconds of clock skew for `nbf`, `iat`, and `exp`.
- Reject expired/not-yet-valid tokens, tokens issued implausibly in the future, and tokens whose `exp - iat` exceeds the configured resource maximum plus clock skew.
- The validator's default maximum is 90 minutes so normally issued Entra access tokens are accepted. The maximum is explicitly configurable from 10 minutes through 24 hours. An operator may select the 10-minute hardening target only after the corresponding Entra policy is explicitly provisioned and verified; the application does not assume that policy exists. Microsoft documents the 10-minute configurable minimum and normal 60-to-90-minute range ([configurable token lifetimes](https://learn.microsoft.com/en-us/entra/identity-platform/configurable-token-lifetimes), [access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens)).

## Identity and correlation propagation

| Identity | Source | Propagation rule |
| --- | --- | --- |
| Entra directory | validated `tid` | Must equal environment allowlist; never accepted from an unsigned header |
| Entra user | validated `oid` with `tid` | Preserved by OBO; mapped server-side to one active RegImpact `UserRecord` |
| RegImpact user/organization | database mapping from `(tid,oid)` | Never taken from `preferred_username`, email, or caller-selected `X-Organization-ID` |
| Calling client | validated `azp` | Must be allowlisted per audience/scope; persisted in audit |
| Service principal | validated `idtyp=app`, `oid`, `azp`, `roles` | Mapped server-side to one approved service/organization grant; never mapped to a human |
| Request correlation | `traceparent`, bounded `X-Request-ID` | Forward trace ID across hops; each service creates a span; identifiers are not authorization inputs |

The existing middleware already creates/propagates `traceparent`, `X-Trace-ID`, and `X-Request-ID`, while authentication sets actor and organization log context (`apps/api/src/regimpact/main.py::request_context`; `apps/api/src/regimpact/auth.py::get_current_user`; `apps/api/src/regimpact/observability.py`). Implementation must add client ID, principal type, external subject, scopes/roles, and OBO correlation to structured logs and durable audit without logging tokens or raw authorization headers.

## Token lifetime, caching, revocation, and shutdown

### Lifetime and caches

- Entra access tokens accepted by these applications must satisfy `exp`/`nbf` and the configured `exp - iat` maximum. The validator defaults to 90 minutes; 10 minutes is an explicit post-policy hardening setting, not an assumed platform default.
- The console's opaque application session has a 30-minute idle and eight-hour absolute maximum, subject to stricter Conditional Access sign-in frequency.
- Browser cookies contain only an opaque session ID and are HTTP-only, Secure outside local, SameSite, path-bound, and CSRF-protected.
- Console token caches are encrypted server-side and partitioned by environment, session, `(tid,oid)`, client, resource, and scope set. No user token is cached globally by email.
- Companion OBO cache entries are partitioned by environment, originating session/user assertion hash, downstream resource, and scope set. OBO refresh tokens are not requested or stored; Microsoft notes that OBO token acquisition does not store refresh tokens ([MSAL OBO guidance](https://learn.microsoft.com/en-us/entra/msal/dotnet/acquiring-tokens/web-apps-apis/on-behalf-of-flow)).
- App-only tokens are cached by managed-identity/client/resource/role context only until the SDK refresh window. Tokens are never persisted in source control, CI artifacts, browser storage, application logs, or durable audit.

### Revocation

- RegImpact rechecks the active local user, organization mapping, and current role on every request, preserving the safety property of current `get_current_user` (`apps/api/src/regimpact/auth.py::get_current_user`; `apps/api/tests/test_auth.py::test_signed_token_resolves_database_identity_and_rejects_tampering`).
- Removing an enterprise-app assignment, disabling a user/service principal, removing consent/app-role assignment, deleting a federated credential, disabling a local user/service grant, or changing local role denies new tokens or the next local authorization check.
- Default JWT access tokens are not assumed to be immediately revocable. The configured maximum and current-state lookup bound exposure. Continuous Access Evaluation may be adopted later only after both resource and clients implement claims challenges; it is not relied on for Phase 1 ([CAE](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-continuous-access-evaluation)).
- Server-side caches are purged on logout, local disablement, role/membership change, client disablement, deployment rollback, and security incident.

### Emergency shutdown

The production runbook must provide all of these controls:

1. set `REGIMPACT_COMPANION_AUTH_ENABLED=false` at FastAPI and companion, denying the companion client ID while preserving console access;
2. remove/disable the companion enterprise application or service principal;
3. remove companion delegated grants, app-role assignments, and federated identity credentials;
4. disable or detach the companion managed identity and scale the companion workload to zero;
5. block companion-to-API private network traffic;
6. purge console/companion token caches and revoke user sessions when user compromise is suspected; and
7. retain security/audit evidence with token identifiers only as one-way hashes.

## Future implementation: required Azure resources and configuration

No resource is created by this ADR. Implementation requires:

- three environment-specific Entra app registrations and enterprise applications listed above;
- exposed delegated scopes and application roles from the matrices;
- token-claim configuration that emits the required v2 `idtyp` principal-type claim; deployment validation must confirm all other required claims in the token/claim matrix;
- admin consent and preauthorization limited to the approved console/companion clients;
- enterprise-app assignment required for users/groups;
- Conditional Access requiring MFA and approved sign-in/session policy;
- an explicit token-lifetime policy only if the operator chooses a validator maximum below the normal Entra lifetime range;
- distinct user-assigned managed identities for console, companion, and FastAPI rather than the current shared workload identity (`infra/main.bicep::identity`, `web`, `api`);
- federated identity credentials from each workload identity to its confidential app registration, with `api://AzureADTokenExchange` audience;
- managed-identity app-role assignments for any approved app-only calls;
- private companion and FastAPI ingress/DNS/network policy; the current API is already internal but no companion path exists (`infra/main.bicep::api`, `web`);
- Key Vault only for token-cache encryption material or certificate fallback, not a shared JWT/client secret;
- environment configuration for tenant ID, issuer, console/companion/API client IDs, application ID URIs, scopes, roles, redirect/logout URIs, authorized clients, JWKS cache/skew limits, and auth migration flags;
- alerts for exchange failure, invalid audience/issuer/client, cross-tenant denial, unknown signing key, rate limit, and companion kill-switch use; and
- deployment-policy checks proving production rejects legacy/demo/local issuers.

Current Bicep only provisions one managed identity and one `jwt-secret`, and passes the latter to all backend workloads (`infra/main.bicep::identity`, `jwtSecretResource`, `commonSecrets`, `commonEnv`). Those resources remain unchanged in this task.

## Local development and CI

### Local development

- Use a dedicated local OIDC test issuer/emulator with locally generated asymmetric keys, the same three audiences, the same scope/role semantics, and short-lived tokens.
- Production/staging validators must never trust the local issuer or keys. Local validators trust only the explicitly configured loopback issuer.
- Local console uses the same authorization-code/PKCE and server-session pattern where practical. Deterministic tests may mint test tokens directly through a test-only helper.
- Existing `legacy_headers` and demo login may remain for unrelated legacy tests/local demo only; neither is a valid companion path (`apps/api/src/regimpact/auth.py::get_current_user`; `apps/api/src/regimpact/auth_api.py::demo_login`; `docker-compose.yml::api`).
- Local clients and keys are distinct from staging/production and contain no Azure secret.

### CI

- Start an ephemeral OIDC issuer or generate an ephemeral RSA key pair and metadata/JWKS fixture per test run.
- Test issuer, tenant ID, audiences, client IDs, scopes, app roles, and users are fixed fixtures; private keys never leave the job and are not uploaded.
- CI exercises the production validator and authorization policy, with external network disabled for deterministic unit tests and a controlled JWKS mock for rotation/outage tests.
- CI keeps existing secret scanning and environment-file rejection (`.github/workflows/quality.yml::infrastructure-validation`).
- An optional staging integration job uses real Entra app registrations and synthetic users; its federated credentials are environment-protected and no production grant is available.

## Migration and rollback plan

### Migration phases

| Phase | Change | Entry/exit gate |
| --- | --- | --- |
| 0. Register and observe | Create environment-specific Entra registrations, scopes/roles, assignments, UAMIs, federation, Conditional Access, token policy, and private DNS/network design | Security reviews manifests/consent; no application traffic changes |
| 1. Dual validator | Add Entra v2 validation, external identity mapping, scopes, service principal model, audit context, and kill switch while retaining legacy HS256 for the existing console only | Automated audience/issuer/scope/RBAC/tenant tests; legacy tokens cannot enter companion paths |
| 2. Console cutover | Move login to Entra auth code + PKCE, opaque server session, and API-audience tokens; stop forwarding `aud=regimpact-web` tokens | Console/API staging regression, logout/cache purge, role/disable tests; no browser access token |
| 3. Companion delegated canary | Enable console -> companion token and companion OBO -> API for allowlisted synthetic tenant/users and read scopes | OBO, audit, correlation, tenant, threat, rate-limit, and retrieval acceptance criteria pass |
| 4. Tenant rollout | Expand read-only companion allowlist with per-tenant kill switch | Operational/security sign-off and measured denial/error rates |
| 5. Remove legacy issuer | Disable credential token issue and HS256 validation; remove `REGIMPACT_JWT_SECRET` from workloads/Key Vault after retention window | No legacy token use in telemetry for two maximum session windows; rollback package verified |
| 6. Optional app-only/read writes | Separately enable approved app roles or delegated write scopes | Separate acceptance and business/security approval for each permission |

During Phase 1, legacy acceptance is restricted by issuer, exact `aud=regimpact-web`, internal console call path, and feature flag. It never accepts companion clients, Entra scopes, or app roles. Entra and legacy identities cannot be merged by email.

### Rollback

- Every phase has independent feature flags for Entra console login, Entra API validation, companion client acceptance, OBO, app-only roles, and individual scopes.
- Before Phase 5, rollback disables companion/OBO, purges exchanged-token caches, and returns the console to the last verified legacy path without allowing legacy tokens at the companion.
- After Phase 5, routine rollback stays Entra-only and deploys the last verified Entra-capable application revision. Re-enabling HS256 requires an emergency security decision, restoration of a versioned Key Vault secret, companion shutdown, and a time-bounded incident plan; it is not an automatic deployment rollback.
- Removing or disabling the companion client ID, its grants/FIC/app roles, and private network access is the authoritative companion rollback and does not require disabling console/API access.
- Database identity mappings and audit records are retained through rollback; tokens and token-cache contents are not.

## Threat analysis

| Threat | Relevant attack | Required control and test |
| --- | --- | --- |
| Token replay | Stolen bearer token replayed from another service/session | Resource-specific audiences, configured bounded lifetime, TLS/private ingress, server-only caches, session partitioning, `uti` hash telemetry, optional sender-constrained tokens later; replay exercise |
| Confused deputy | Companion uses a valid user token to call a route/client the user did not intend | OBO to a distinct audience, exact requested scope, `azp` allowlist, scope + current RBAC + resource ownership, no `.default` blanket request for delegated operations; negative client/scope tests |
| Audience confusion | Console/companion/Graph token accepted at FastAPI | Exact v2 client-ID `aud`, tenant issuer, resource-owned validation, separate app registrations; cross-audience matrix tests |
| Privilege escalation | Viewer obtains analyst/admin effect; service acts as user; companion asks for broader scope | Current DB role recheck, delegated `scp` versus app `roles`, `idtyp`, no service write roles, client preauthorization, deny unknown scope, separation-of-duties tests |
| Leaked confidential credential | Client secret/certificate or managed identity is stolen | Managed-identity federation, distinct UAMI per workload/environment, no production secrets, FIC/app-role removal, Key Vault certificate fallback only, workload/network kill switch |
| Cross-tenant access | Foreign `tid`, guest home tenant, forged organization header, or foreign resource ID | Single configured `tid`, tenant-specific authority, `(tid,oid)` local mapping, one organization per user/service in Phase 1, resource ownership queries, no trusted organization header, cross-tenant tests |
| Signing-key/JWKS attack | Attacker supplies key URL, unknown key, algorithm confusion, or exploits metadata outage | Pinned tenant discovery, RS256 only, ignore token key URLs, bounded known-key cache, one refresh on unknown `kid`, fail closed after ceiling; rotation/outage tests |
| OBO assertion misuse | ID token/app-only token exchanged, assertion forwarded, or token cached across users | Access-token-only assertion, delegated scope required, confidential client proof, session/assertion-partitioned cache, no refresh token, OBO negative tests |
| Consent/grant expansion | Operator grants broad delegated scopes/app roles | IaC/manifests under review, admin consent inventory, no write app roles, deployment drift check, periodic access review |
| Correlation spoofing | Caller uses request ID to impersonate identity or hide audit chain | Correlation is never authorization input; bounded/sanitized headers; actor/client/tenant come from validated token and server mapping |

## Implementation phases and ownership

1. **Identity platform:** register applications/service principals, scopes, app roles, assignments, token policy, Conditional Access, and managed-identity federation.
2. **RegImpact authentication:** implement Entra validation, principal types, `(tid,oid)` mapping, authorized-client policy, scope/app-role dependencies, service grants, and stable denial codes.
3. **Console:** implement Entra code + PKCE, opaque session, encrypted token cache, API/companion token acquisition, CSRF, logout, and legacy cutover.
4. **Companion boundary:** deploy separate UAMI/app registration, companion validation, OBO, cache isolation, correlation, rate limits, and kill switch. The companion repository is not created by this task.
5. **Audit and operations:** add exchange/call audit context, dashboards/alerts, revocation and JWKS outage runbooks, private networking, and rollback automation.
6. **Canary and rollout:** synthetic staging, read-only tenant canary, security review, measured rollout, then legacy retirement.

## Acceptance criteria and automated tests

### Identity-provider and protocol

- Authorization code + PKCE validates `state`, `nonce`, redirect URI, code verifier, tenant, and confidential-client proof.
- Companion OBO succeeds only with a valid companion-audience user access token and returns a RegImpact-API-audience token with only requested/consented delegated scopes.
- ID tokens, app-only tokens, wrong-resource tokens, expired assertions, foreign-tenant tokens, and public/unregistered clients cannot be used for OBO.
- App-only tokens are acquired through the intended managed identity and contain only approved application roles.

### Validator

- Tests cover exact issuer, `tid`, v2 GUID audience, `azp`, `idtyp`, `oid`, `scp`, `roles`, `iat`, `nbf`, `exp`, `uti`, signature, `kid`, `typ`, and `ver`.
- Reject HS256, `none`, wrong RSA algorithm, wrong/unknown audience, `/common` issuer, personal account tenant, unknown client, malformed/duplicate claims, overlong lifetime, and excessive clock skew.
- JWKS tests cover normal cache, scheduled refresh, key overlap, unknown-`kid` refresh, poisoned key URL, metadata/JWKS outage, last-known-good ceiling, and fail-closed expiry.

### Authorization and tenancy

- Every scope/application-role row has allow and deny tests for client, principal type, current local role, service grant, organization, and route.
- Existing `viewer`, `analyst`, and `admin` behavior remains intact; a viewer cannot gain reviewer/admin effects and a service cannot satisfy `ReviewerUser`/`AdminUser` (`apps/api/tests/test_auth.py::test_viewer_cannot_create_controls`, `test_operational_snapshot_is_admin_only`).
- Foreign organizations/resources remain hidden and side-effect free (`apps/api/tests/test_read_api.py::test_read_endpoints_enforce_organization_boundary`; `apps/api/tests/test_review_workflow.py::test_tenant_cannot_read_or_decide_another_tenants_work`; `apps/api/tests/test_retrieval.py::test_tenant_isolation_applies_to_index_and_search`; `apps/api/tests/test_agent_workflow.py::test_tenant_boundary_hides_foreign_obligation`).
- Email/name changes do not change identity mapping; disabled local users, changed roles, removed mappings, disabled clients, and revoked service grants deny the next call.

### Browser, caches, audit, and operations

- No access/refresh token appears in browser storage, page payload, URL, readable cookie, logs, traces, errors, audit, or CI artifacts.
- Token caches are encrypted, environment/session/user/resource/scope partitioned, expire correctly, purge on logout/revocation, and never return one user's token to another.
- `traceparent` and `X-Request-ID` correlate console -> companion -> API; client, principal, user/service, organization, scope/role, resource, result, and one-way `uti` hash appear in required logs/audit.
- Invalid audience/client/scope/tenant and OBO failures produce stable non-sensitive `401`/`403` codes and alertable metrics.
- Rate-limit tests cover login, token exchange, evidence search, and denied-call floods.
- Kill-switch, grant removal, FIC removal, client disablement, cache purge, JWKS outage, network block, and rollback drills pass in staging.

### Regression and release gates

- Existing authentication, RBAC, tenant, review, workflow, API error, and observability tests remain green, including `apps/api/tests/test_auth.py`, `test_read_api.py`, `test_retrieval.py`, `test_review_workflow.py`, `test_agent_workflow.py`, `test_api_contract.py`, and `test_observability.py`.
- Bicep/deployment checks prove separate identities, exact app IDs/issuers, no production legacy/demo mode, private API/companion connectivity, no shared JWT/client secret, and environment isolation.
- Independent threat-model and security reviews approve the token manifests, consent grants, Conditional Access, service roles, emergency shutdown, migration, and rollback evidence before production.

## Operator and business choices still required

These are explicit deployment/business inputs, not unresolved architecture mechanisms:

1. The production Entra directory tenant ID and named identity-platform owner.
2. Which Entra groups receive console/companion enterprise-app assignment and how B2B guests are approved/offboarded.
3. Whether the tenant will retain the 90-minute validator maximum or explicitly provision and verify a shorter Entra token-lifetime policy; Conditional Access/MFA approval remains required.
4. The exact production/staging application client IDs, Application ID URI names, redirect/logout URIs, and verified domains.
5. The approved initial tenant/user canary and the business owner who may activate or stop companion access.
6. Whether `Evidence.Read.All` app-only access is needed at all in Phase 1. Default is no app-only companion access.
7. Whether service identities will ever need `Reviews.Read.All` or `Workflows.Read.All`; both remain unassigned until separately approved.
8. Audit retention/export destination, security-monitoring owner, and privacy approval for query/filter hashes and evidence identifiers.
9. Whether the managed-identity federated client assertion is supported by the selected Node/Python authentication libraries at implementation time; approved fallback is a rotated Key Vault certificate, not a client secret.
10. The maintenance window and evidence threshold for permanently deleting the legacy HS256 secret after cutover.

Future multitenant SaaS identity, one human in multiple RegImpact organizations, companion-mediated mapping decisions, workflow approvals, and autonomous writes require separate decisions. They are not implicitly authorized here.

## Consequences

### Positive

- Entra becomes the only production issuer and supplies workforce MFA/Conditional Access, asymmetric keys, app consent, OBO, managed identities, and central client/user controls.
- Each hop receives a token for its own audience, eliminating browser-token passthrough and reducing confused-deputy risk.
- Delegated scopes and current RegImpact RBAC remain separate controls; application roles provide an explicit non-human path without fake users.
- Environment-specific registrations, distinct managed identities, kill switches, and narrow rollback reduce blast radius.

### Costs

- The console authentication model and FastAPI validator must change materially.
- Three app registrations per environment, consent, token policy, federated credentials, app-role assignments, private networking, audit enrichment, caches, runbooks, and security testing require platform ownership.
- The one-organization-per-user/service restriction limits initial deployment and may require a future membership model.
- A shorter operator-selected token lifetime increases token-endpoint traffic and makes resilient, correctly partitioned server caches mandatory.

## Compliance with prior decisions

This ADR resolves the identity-provider and exchange mechanism left open by `docs/adr/companion-authentication-contract.md`. It preserves that ADR's distinct audiences, no-passthrough rule, scope-plus-RBAC intersection, human/service separation, tenant checks, audit requirements, and read-only Phase 1 boundary. It changes no application code, migrations, infrastructure, API behavior, or companion repository.
