# v0.3A release audit

## Outcome

v0.3A introduces database-backed authentication and organization-scoped RBAC without changing
the evidence, mapping, or append-only review decision models delivered in v0.2.6.

## Security controls

- Memory-hard scrypt password hashing; plaintext passwords are never persisted or returned.
- Signed access tokens with issuer, audience, issued-at, and expiry validation.
- Active user, organization, and current database role are revalidated on every API request.
- Organization and actor identifiers are derived from identity rather than caller headers.
- HTTP-only, same-site browser cookie with secure transport enabled in production builds.
- Admin-only configuration and user provisioning.
- Analyst/admin review decisions and mapping suggestions.
- Viewer read-only experience and API enforcement.
- Successful login and user-creation audit events.
- Production startup rejects legacy header mode and the bundled development secret.

## Verification gates

- Python syntax and import compilation
- Alembic forward and reverse migration path
- Authentication success and failure behavior
- Viewer denial on protected mutations
- Existing deterministic domain and API regression suite
- Ruff and MyPy checks
- Frontend ESLint, TypeScript, and production build
- PostgreSQL-backed integration suite and idempotent demo seed

## Artifact verification result

The reviewed source artifact passed 55 Python tests, Ruff, MyPy across 35 source files, frontend
ESLint, TypeScript validation, and a Next.js production build. Alembic generated valid PostgreSQL
upgrade and downgrade SQL for the v0.3A migration. A live Docker/PostgreSQL smoke test remains the
acceptance check on the target workstation because the artifact build environment did not expose a
Docker daemon.

## Deferred controls

Refresh-token rotation, MFA, password recovery, external OIDC, centralized revocation, and login
rate limiting are intentionally deferred. v0.3A must not be described as internet-ready identity
management until those controls or a managed identity provider are introduced.
