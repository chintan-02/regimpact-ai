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

## External identity mapping

After cryptographic validation, Entra users resolve through `external_identities` by the exact
normalized tuple `(provider=entra, configured tenant UUID, oid UUID)`. The mapping references an
existing local user and organization through a tenant-consistent composite foreign key. Database
constraints prevent one external identity from resolving to multiple users and prevent one local
user from receiving multiple identities for the same provider and tenant. User deletion is
restricted while a mapping exists; mappings are disabled rather than deleted.

Malformed, missing, unknown, ambiguous, or disabled mappings fail with the generic unauthorized
response. The resolver never falls back to `oid == UserRecord.id` and never creates a user or
mapping. Organization, tenant membership, current role, and permissions come only from the active
local database user and existing resource queries—not from `oid`, `sub`, email, groups, delegated
scopes, application roles, or caller headers.

Existing database-backed administrators may create, list, and disable mappings through
`POST/GET /api/v1/auth/external-identities` and
`POST /api/v1/auth/external-identities/{mapping_id}/disable`. The configured Entra tenant is always
supplied by the server. Listing is organization- and tenant-scoped with `limit=50` by default,
`limit=1..100`, and `offset=0..10000`. Responses expose a 12-character SHA-256 fingerprint for
operator comparison, not the external `oid`. Request bodies reject unexpected fields. Self-linking,
cross-organization targets, re-linking, destructive deletion, non-admin users, inactive users, and
service principals are denied. Successful changes, authorization denials, and conflicts create
audit events containing local mapping/user IDs and safe reasons, never the external `oid`, token,
or subject. Database conflicts are rolled back before the rejection audit is committed, keeping the
session usable and the denial record durable.

The unique `(provider, tenant_id, user_id)` constraint is intentional: one local user may have at
most one identity for a provider in a tenant. Together with unique
`(provider, tenant_id, external_oid)`, it prevents silent re-linking in either direction. The
composite user/organization foreign key prevents a mapping from crossing the local organization
boundary.

### First-administrator bootstrap

Normal API self-linking remains prohibited. A deployment with only one local administrator uses
the offline operator command while the application is explicitly in `dual` mode. It connects
directly to PostgreSQL, takes a row lock on the existing administrator, and can create only the
first Entra mapping in the database. The target must already be an active local administrator; the
command does not create users or infer organization, role, or permissions. Any existing Entra
mapping disables this path permanently. Success and database-conflict outcomes write durable audit
events without the external `oid`.

Run the migration first, set the full validated Entra configuration, retain the legacy signing
secret, and substitute only the placeholders below:

```bash
REGIMPACT_DATABASE_URL='<POSTGRESQL_CONNECTION_URI>' \
REGIMPACT_ENVIRONMENT='<ENVIRONMENT>' \
REGIMPACT_AUTH_MODE='dual' \
REGIMPACT_JWT_SECRET='<EXISTING_LEGACY_SIGNING_SECRET>' \
REGIMPACT_ENTRA_TENANT_ID='<ENTRA_TENANT_UUID>' \
REGIMPACT_ENTRA_ISSUER='https://login.microsoftonline.com/<ENTRA_TENANT_UUID>/v2.0' \
REGIMPACT_ENTRA_API_AUDIENCE='<REGIMPACT_API_CLIENT_UUID>' \
REGIMPACT_ENTRA_JWKS_URL='https://login.microsoftonline.com/<ENTRA_TENANT_UUID>/discovery/v2.0/keys' \
python -m regimpact.external_identity_cli bootstrap \
  --user-id '<LOCAL_ADMIN_USER_UUID>' \
  --entra-oid '<ENTRA_USER_OBJECT_UUID>' \
  --acknowledge 'I ACKNOWLEDGE THIS CREATES THE FIRST ENTRA ADMIN MAPPING'
```

The command prints only local mapping and user IDs. It never prints the Entra object ID, token,
secret, or claims.

### Cutover preflight and rollback

Run the read-only preflight with the same environment before changing `dual` to `entra`:

```bash
REGIMPACT_DATABASE_URL='<POSTGRESQL_CONNECTION_URI>' \
REGIMPACT_ENVIRONMENT='<ENVIRONMENT>' \
REGIMPACT_AUTH_MODE='dual' \
REGIMPACT_JWT_SECRET='<EXISTING_LEGACY_SIGNING_SECRET>' \
REGIMPACT_ENTRA_TENANT_ID='<ENTRA_TENANT_UUID>' \
REGIMPACT_ENTRA_ISSUER='https://login.microsoftonline.com/<ENTRA_TENANT_UUID>/v2.0' \
REGIMPACT_ENTRA_API_AUDIENCE='<REGIMPACT_API_CLIENT_UUID>' \
REGIMPACT_ENTRA_JWKS_URL='https://login.microsoftonline.com/<ENTRA_TENANT_UUID>/discovery/v2.0/keys' \
python -m regimpact.external_identity_cli preflight \
  --acknowledge-legacy-rollback \
  'I ACKNOWLEDGE LEGACY ROLLBACK REQUIRES RESTORING LEGACY MODE AND ITS SECRET'
```

The preflight performs no writes and no network calls. It fails unless the Entra configuration is
valid, migration `20261115_0013` is current, mappings are unambiguous and tenant-consistent, and at
least one active mapping resolves to an active local administrator. A deployment runbook must make
this command a required gate before enabling `entra`; retaining the previous legacy secret in the
approved secret store is part of the acknowledgement.

If the initial bootstrap itself must be undone, first keep or restore `legacy`/`dual`, then use the
bootstrap-only rollback. It can disable only an active mapping whose creator is the offline
bootstrap actor; it cannot alter API-created mappings and cannot run in `entra` mode:

```bash
REGIMPACT_DATABASE_URL='<POSTGRESQL_CONNECTION_URI>' \
REGIMPACT_ENVIRONMENT='<ENVIRONMENT>' \
REGIMPACT_AUTH_MODE='dual' \
REGIMPACT_JWT_SECRET='<EXISTING_LEGACY_SIGNING_SECRET>' \
REGIMPACT_ENTRA_TENANT_ID='<ENTRA_TENANT_UUID>' \
REGIMPACT_ENTRA_ISSUER='https://login.microsoftonline.com/<ENTRA_TENANT_UUID>/v2.0' \
REGIMPACT_ENTRA_API_AUDIENCE='<REGIMPACT_API_CLIENT_UUID>' \
REGIMPACT_ENTRA_JWKS_URL='https://login.microsoftonline.com/<ENTRA_TENANT_UUID>/discovery/v2.0/keys' \
python -m regimpact.external_identity_cli rollback-bootstrap \
  --mapping-id '<BOOTSTRAP_MAPPING_UUID>' \
  --acknowledge 'I ACKNOWLEDGE THIS DISABLES THE BOOTSTRAP ENTRA ADMIN MAPPING'
```

For a cutover rollback, restore `REGIMPACT_AUTH_MODE=dual` (or `legacy`) together with the retained
legacy signing secret through the existing deployment configuration, redeploy, and run the
preflight again before any later Entra-only attempt. Normal mapping changes continue to use the
admin API. A user can never disable their own currently authenticated mapping. In `entra` mode, an
administrator also cannot disable another administrator's mapping when it is the last active admin
mapping for that organization and configured tenant. In `legacy` or `dual`, the legacy
authentication path remains the documented recovery route.

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
