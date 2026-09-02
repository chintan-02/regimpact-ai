# Observability and operational response

RegImpact AI v0.3B adds service telemetry without weakening tenant isolation. Logs and trace
context support investigation; metrics use bounded labels so user, tenant, document, and request
identifiers cannot create unbounded time-series cardinality.

## Signals

- JSON logs include UTC timestamp, severity, service, event, request ID, trace ID, route, method,
  response status, and duration. Authenticated requests also include actor and organization IDs.
- Uvicorn's duplicate access stream is disabled because the request middleware emits the canonical
  structured access event. Uvicorn lifecycle messages may still appear during process startup.
- `traceparent` is accepted and propagated using the W3C trace-context format. Every response also
  returns `X-Trace-ID` and `X-Request-ID` for support correlation.
- `/metrics` exposes Prometheus-format request totals, in-flight requests, latency histograms, and
  process uptime. Metrics contain no user, tenant, raw URL, document, or request-ID labels.
- `/health` is a liveness check and never tests downstream dependencies.
- `/startup` confirms the API process initialized.
- `/ready` checks PostgreSQL and Redis and returns `503` when either critical dependency fails.
- `/api/v1/operations/snapshot` is admin-only and supplies the Operations dashboard with request,
  ingestion, outbox, and uptime signals.

## Local verification

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/startup
curl -i http://localhost:8000/ready
curl -s http://localhost:8000/metrics | head -40
docker compose logs api --tail=20
```

The in-process metrics registry resets when the API restarts. Production deployment should scrape
metrics into a durable monitoring backend and export trace spans to a managed OpenTelemetry target.
That external infrastructure belongs to v0.3C rather than being embedded in the application image.

## Initial alert guidance

- readiness unavailable for two consecutive probe windows;
- HTTP 5xx ratio above 2% for five minutes;
- p95 request latency above one second for ten minutes;
- any dead-letter ingestion job;
- sustained unpublished outbox backlog for more than five minutes.

Thresholds are starting points and must be tuned against production traffic and service objectives.
