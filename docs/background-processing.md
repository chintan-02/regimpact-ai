# Background processing

## Delivery model

The API never publishes a worker message inside the database transaction. It writes the ingestion job, audit event and outbox event atomically. A separate dispatcher claims unpublished outbox rows with `FOR UPDATE SKIP LOCKED`, publishes to Redis/Dramatiq, then marks the row published.

This provides at-least-once delivery. All worker handlers must therefore be idempotent.

## Runtime processes

- API: validates uploads and writes queued jobs.
- Dispatcher: drains the transactional outbox.
- Worker: processes ingestion and regulatory-source queues.
- Scheduler: claims due sources and creates source-check outbox events.
- Redis: durable queue broker with append-only persistence for local operation.
- PostgreSQL: source of truth for job, attempt, source-check and audit state.

## Failure behaviour

- Temporary storage failures use bounded exponential retry.
- Permanent validation/parser failures become `failed` jobs.
- Ingestion retries stop at the database-configured maximum and become `dead_letter`.
- Source checks use conditional requests and bounded exponential scheduling after failure.
- Outbox events stop automatic publication after ten failures and appear in queue health.
- Message delivery may be duplicated; content hashing and job state make processing idempotent.

## Production constraints

Redis is not the source of truth. Queue depth is operational state; authoritative status remains in PostgreSQL. Production deployment must add Redis authentication/TLS, network isolation, managed persistence, metrics and alerting.

The durable retry, lease, dead-letter, and recovery contract is documented in
[`ingestion-reliability.md`](ingestion-reliability.md).
