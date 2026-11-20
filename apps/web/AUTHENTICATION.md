# Phase A1 local console authentication

The new `/api/auth/entra/*` routes implement the console-owned Authorization Code + S256 PKCE,
opaque session, CSRF and companion-audience token-cache boundary. They are isolated from the
pre-existing credential login and bearer-cookie forwarding routes. Phase A1 does not replace or
authorize those legacy routes.

Authentication is disabled unless `REGIMPACT_CONSOLE_ENTRA_ENABLED=true` and every required
`REGIMPACT_CONSOLE_*` value in the repository `.env.example` is valid. Local and CI tests use a
loopback mock issuer, ephemeral signing keys, a synthetic confidential-client assertion provider
that is constructible only in the `test` environment, and the dedicated `console-redis` service.
Staging and production reject loopback issuers, insecure cookies and synthetic assertions.

Session, transaction, ID-token, refresh-token and companion access-token records are protected
with AES-256-GCM before Redis storage. Redis keys are HMAC-derived and token entries are partitioned
by environment, session, `(tid, oid)`, client, audience and canonical scope set. The browser sees
only an opaque HTTP-only session cookie and a non-secret CSRF token. Logout purges the session and
its indexed token records. Redis, encryption, discovery, JWKS or token-endpoint failures do not
fall back to memory or legacy authentication.

The default confidential-client assertion provider is deliberately unavailable. Phase A2 must
implement and verify the approved distinct console managed-identity federation mechanism, or the
approved Key Vault certificate fallback, against real non-production Entra. No client secret is
supported. This phase does not implement OBO or call the companion.

## Engineering and mentor handoff

**Milestone status:** Phase A1 is implemented and locally verified with mock identity endpoints,
ephemeral keys and real Redis. It proves the console and companion authentication boundaries, not
a live integration between them. Phase A2 is planned, not verified: it must supply real
non-production Entra configuration and approved confidential-client proof before any end-to-end
claim. OBO remains outside Phase A1.

Actual Phase A1 token flow:

```text
Browser -> /api/auth/entra/login -> loopback mock authorize endpoint
Browser <- authorization code + state
Browser -> /api/auth/entra/callback -> mock token endpoint (code + PKCE verifier)
Console <- ID token + companion-audience access token (AT-C)
Console -> encrypted session and AT-C cache -> dedicated console-redis
Browser <- opaque HttpOnly session cookie + non-secret CSRF cookie

Synthetic AT-C fixture -> CompanionTokenValidator -> test-only /__test/auth/probe
                         (no console -> companion HTTP call in Phase A1)
```

Key console modules are `lib/auth/config.ts`, `assertion.ts`, `oidc.ts`, `store.ts` and
`runtime.ts`, with browser adapters under `app/api/auth/entra/`. The primary evidence is in
`tests/auth-config.test.ts`, `auth-oidc.test.ts`, `auth-routes.test.ts`, `auth-store.test.ts` and
the real-Redis `auth-store.integration.test.ts`. Companion validation is recorded in its ADR 0004
and exercised by `src/regimpact_companion/auth.py` and `tests/test_auth.py`.

Debug the boundary, not the happy-path symptom:

- A generic callback failure: trace state consumption, redirect origin, PKCE verifier, client
  assertion availability, token response and ID-token validation in that order.
- A missing session: check cookie policy, encrypted Redis record, idle/absolute expiry and key-ring
  availability; do not add an in-memory or legacy fallback.
- A companion denial: trace `alg`/`kid`, issuer, audience, `tid`, `azp`, `idtyp`, time claims and
  `companion:access`; never infer a RegImpact role from those claims.
- Any outage or malformed response: confirm the client receives a generic denial and logs contain
  event/category metadata, not codes, tokens, assertions, cookies or claims.

Explain -> Trace -> Debug exercises:

1. Explain why AT-C never reaches the browser, trace its storage key and encryption boundary, then
   debug a cache miss without logging token material.
2. Explain single-use callback state, trace two concurrent callback attempts, then identify the
   atomic operation that makes one fail closed.
3. Explain why a valid companion token grants no RegImpact authorization, trace the companion
   claim checks, then debug a wrong-`azp` denial while preserving the generic `401` contract.

Local verification:

```bash
docker compose up -d console-redis
cd apps/web
REGIMPACT_TEST_CONSOLE_REDIS_URL=redis://127.0.0.1:6380/0 npm test
npm run lint
npm run typecheck
npm run build
```
