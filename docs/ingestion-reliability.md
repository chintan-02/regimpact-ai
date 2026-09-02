# Ingestion reliability

v0.3D makes document ingestion recoverable under worker crashes, transient storage failures,
broker outages, and duplicate delivery.

## State and ownership

- A database row remains the source of truth for each content-addressed ingestion.
- A worker must acquire an expiring UUID lease before processing. A live lease rejects a duplicate
  worker; an expired lease may be reclaimed after a crash.
- Successful jobs are idempotent. The existing organization, regulation, and content-hash unique
  constraint prevents duplicate jobs and version content hashes prevent duplicate versions.

## Failure policy

- Validation and extraction errors are permanent and stop as `failed`.
- Storage, connection, and timeout errors are transient. They use exponential backoff with jitter,
  persisted attempt counters, and a configured maximum.
- Exhausted transient failures move to `dead_letter`. Broker delivery events independently retry
  and move to their own dead-letter state after ten attempts.

## Recovery

Administrators can replay failed or dead-letter ingestion jobs from the ingestion ledger. Replay
resets retry state, creates a fresh transactional outbox event, increments the replay counter, and
records `ingestion.replayed` in the audit history. Analysts and viewers cannot replay work.

## Operations

The ingestion ledger exposes attempts, retry time, failure class, replay count, and recovery action.
The Operations page reports pending and dead-letter outbox events. Alerts should be raised for any
dead-letter item, sustained outbox backlog, or processing lease older than its configured duration.

## Remaining production work

Azure Monitor alert rules and automated runbook notifications belong with the live environment
configuration. They must be calibrated using production traffic instead of hard-coded demo limits.
