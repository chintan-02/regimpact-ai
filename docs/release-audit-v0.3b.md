# v0.3B release audit

## Scope

This phase adds structured logging, trace correlation, low-cardinality metrics, health semantics,
and an administrator operational dashboard to the accepted v0.3A r2 authentication baseline.

## Security and reliability decisions

- The operational snapshot is restricted to administrators.
- Prometheus labels exclude tenant, user, request, source URL, and document identifiers.
- Readiness reports dependency category and state without returning credentials or exception text.
- Liveness is independent of PostgreSQL and Redis so an orchestrator does not restart a healthy
  process merely because a dependency is temporarily unavailable.
- Existing admin, analyst, and viewer authorization behavior is unchanged.
- Duplicate plain-text Uvicorn access records are disabled; the structured middleware event is the
  canonical per-request record.

## Acceptance criteria

- JSON logs are machine-readable and correlate request and trace identifiers.
- Incoming valid W3C trace IDs are preserved while a new response span ID is generated.
- Prometheus metrics include traffic, status, latency, in-flight request, and uptime signals.
- Docker waits for API readiness before starting the web application.
- Only administrators can load the Operations dashboard data.
- Backend tests, Ruff, MyPy, frontend lint, TypeScript, production build, and Docker verification pass.
