# Authentication and role-based access control

v0.3A replaces client-supplied tenant and actor identities with signed, short-lived access tokens.
The API resolves the organization, actor, and role from the authenticated database user on every
request. The Next.js boundary stores the token in an HTTP-only, same-site cookie so browser
JavaScript cannot read it.
Set `REGIMPACT_COOKIE_SECURE=true` behind HTTPS; local HTTP compose explicitly keeps it false.

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

`REGIMPACT_AUTH_MODE=legacy_headers` exists only for deterministic tests that predate v0.3A. The
application rejects this mode in production.

## Known limits

v0.3A intentionally excludes refresh tokens, password reset, MFA, external OIDC, rate limiting,
and centralized session revocation. Those controls require an external identity provider or a
dedicated session service and should be added before internet-facing production deployment.
