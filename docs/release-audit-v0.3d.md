# v0.3D release audit

Status: reviewed development artifact; not tagged or deployed.

Implemented: durable worker leases, bounded retry with jitter, permanent/transient failure
classification, ingestion and outbox dead-letter states, admin-only audited replay, recovery UI,
operational backlog visibility, migration `20260902_0010`, and reliability regression tests.

Acceptance requires the complete Python and frontend quality suites, Alembic upgrade, Docker health,
seed execution, and an administrator replay smoke test on PostgreSQL/Redis.
