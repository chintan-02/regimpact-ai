# Authentication and role-based access control

RegImpact supports a fail-closed migration from its application-issued HS256 tokens to Microsoft
Entra access tokens. The API resolves the organization, actor, and role from the authenticated
database user on every request. Token scopes and application roles are exposed separately to the
authenticated principal, but neither grants a RegImpact permission in this milestone. Existing
database RBAC and tenant/resource checks remain authoritative.

The current Next.js boundary stores the legacy token in an HTTP-only, same-site cookie so browser
JavaScript cannot read it. Entra browser login and OBO token acquisition are not implemented yet.
Set `REGIMPACT_COOKIE_SECURE=true` behind HTTPS; local HTTP compose explicitly keeps it false.

## Authentication migration modes

`REGIMPACT_AUTH_MODE` has three deployment modes:

| Mode | Accepted bearer tokens | Intended use |
| --- | --- | --- |
| `legacy` | Current `iss=regimpact-api`, `aud=regimpact-web`, HS256 tokens only | Default and existing production behavior until an operator explicitly starts migration |
| `dual` | Legacy tokens plus tenant-specific Entra RS256 access tokens | Time-bounded console migration and validation canary |
| `entra` | Entra RS256 access tokens only | Target state after legacy retirement |

`legacy_headers` remains a non-production test-compatibility mode. Production rejects it. A token
is classified once from its strict JWT structure and algorithm. A failed Entra token is never
retried as legacy, and an RSA public key is never used as an HMAC secret.
The current credential/demo login can issue legacy tokens in `legacy` or `dual`; credential login
is disabled in `entra` mode because the future browser OIDC flow is outside this milestone.

`dual` and `entra` require all of the following settings:

| Setting | Contract |
| --- | --- |
| `REGIMPACT_ENTRA_TENANT_ID` | Configured workforce-directory UUID |
| `REGIMPACT_ENTRA_ISSUER` | Exact `https://login.microsoftonline.com/{tenant-id}/v2.0` issuer |
| `REGIMPACT_ENTRA_API_AUDIENCE` | Exact RegImpact API application client-ID UUID |
| `REGIMPACT_ENTRA_JWKS_URL` | Exact tenant-specific `https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys` endpoint outside tests |
| `REGIMPACT_ENTRA_CLOCK_SKEW_SECONDS` | Validation leeway, from 0 through 300 seconds |
| `REGIMPACT_ENTRA_MAX_TOKEN_LIFETIME_SECONDS` | Maximum `exp - iat`; defaults to 5,400 seconds and permits 600 through 86,400 seconds |
| `REGIMPACT_ENTRA_JWKS_TIMEOUT_SECONDS` | Bounded connect/read timeout, from 0.1 through 30 seconds |
| `REGIMPACT_ENTRA_JWKS_CACHE_SECONDS` | In-memory key-cache lifetime, from 60 through 21,600 seconds |

Entra validation requires RS256, a trusted `kid`, signature through the configured JWKS, exact
issuer/audience/tenant, and valid `iat`, `nbf`, and `exp`. It also requires v2 user tokens with
`tid`, `oid`, `sub`, `azp`, `idtyp=user`, `uti`, and `ver=2.0`. The default maximum lifetime is 90
minutes so normal Entra access tokens are accepted. An operator may reduce it to 600 seconds only
after the corresponding Entra token-lifetime policy has been explicitly provisioned and verified.
`exp` and `nbf` remain mandatory at every setting. JWKS retrieval uses bounded response and key
counts, refreshes once for an unknown `kid`, and fails closed when a trusted key cannot be obtained.
Outside tests, configuration rejects non-Entra hosts, wrong-tenant paths, credentials, fragments,
queries, ports, and non-HTTPS URLs. Authentication errors remain generic to clients; logs contain
only a safe failure category and token family, never the token or claims.

Until a dedicated external-identity mapping is implemented, the validated Entra `oid` must be a
UUID exactly equal to an existing active `UserRecord.id`. A malformed or unknown `oid` is denied;
the validator never auto-provisions a user. The API derives organization, tenant membership,
current role, and permissions only from that database record and existing resource queries, never
from `oid`, delegated scopes, application roles, email, or headers. This is a temporary migration
constraint. The required successor is an explicit table keyed by `(entra_tenant_id, entra_oid)`
with a unique, active association to a local user and organization, lifecycle/audit fields, and no
implicit email matching.

## Roles

| Role | Read evidence | Record decisions | Configure controls and sources |
| --- | --- | --- | --- |
| Viewer | Yes | No | No |
| Analyst | Yes | Yes | No |
| Admin | Yes | Yes | Yes |

Passwords are hashed with memory-hard scrypt and are never stored or logged in plaintext. Successful logins
create audit events. Tokens contain only the user identifier, organization identifier, role, and
standard lifetime claims; authorization is rechecked against the active database user.
Administrators can list and create users for their own organization through the authenticated API;
password hashes are never returned by API contracts.

## Local demonstration

Run migrations before the idempotent demo seed. The compose file includes local-only credentials
for the three reference roles. Override every demo password and `REGIMPACT_JWT_SECRET` outside a
throwaway local environment. The seed refuses to run when the environment is production.

Local/demo deployments remain in `legacy` mode unless an operator supplies a complete test Entra
configuration and explicitly selects `dual` or `entra`. `REGIMPACT_AUTH_MODE=legacy_headers`
exists only for deterministic tests that predate v0.3A. The application rejects this mode in
production.

## Known limits

This milestone validates Entra access tokens but intentionally excludes OBO token acquisition,
browser OIDC login, refresh-token handling, Entra resource provisioning, companion endpoints,
rate limiting, and centralized session revocation. Those controls remain required before the
companion or an internet-facing production deployment is enabled.
