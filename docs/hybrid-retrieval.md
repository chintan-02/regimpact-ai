# Hybrid regulatory evidence retrieval

## Companion retrieval contract

Companion search remains `GET /api/v1/search` with query length 2--500 and a hard result maximum of
50. Before embedding the query, RegImpact verifies that every tenant section has a projection for
the configured model and that indexed section hashes and version relationships match canonical
records. Missing, stale, inconsistent or unavailable configuration returns generic
`503 search_unavailable`.

Search hits include regulation/version/section IDs, immutable version and section content hashes,
source URI/page and model/ranking metadata. Scores rank candidates; they are not evidence or proof.
Resolve a hit with `GET /api/v1/evidence/{section_id}` and the required `version_id`,
`version_content_hash`, and `section_hash` query values. A stale, mismatched, unresolved or
cross-organization reference returns the same `404`. Response text is bounded by
`REGIMPACT_COMPANION_MAX_EVIDENCE_CHARS`; `body_truncated` is explicit. Citation validity does not
establish that a generated claim is supported; claim-support evaluation belongs to the future
companion runtime.

## Contract

v0.2C indexes immutable regulation sections with organization, regulation, version, section, page, source URI, content hash and embedding-model lineage. Search results always return that citation chain; derived ranking data is never treated as the source of truth.

## PostgreSQL retrieval

Production PostgreSQL uses:

- `to_tsvector('english', searchable_text)` with a GIN index for lexical retrieval;
- pgvector `VECTOR(384)` with an HNSW cosine index for vector retrieval;
- reciprocal-rank fusion with rank constant 60;
- mandatory organization and embedding-model filters inside both candidate queries.

The Compose and CI PostgreSQL image includes pgvector. Migration `20260901_0006` installs the extension and creates both indexes.

## Embedding provider

The included `feature-hash-384-v1` provider is deterministic, dependency-free and suitable for contract tests and the local demonstration. It provides vector similarity but is not a neural semantic embedding model and must not be represented as one. It is rejected outside the local environment.

The optional `semantic` installation includes a verified-dimension sentence-transformer adapter, defaulting to `sentence-transformers/all-MiniLM-L6-v2`. Production configuration must select `sentence_transformer`; model loading fails closed if the package is absent or the model does not produce 384-dimensional vectors.

## API

- `POST /api/v1/versions/{version_id}/search-index` indexes a tenant-owned immutable version idempotently.
- `GET /api/v1/search?q=...&limit=...` returns fused scores plus lexical, vector and citation details.

SQLite uses an in-process lexical/cosine adapter only for deterministic tests. PostgreSQL is the authoritative runtime for FTS, pgvector and RRF behavior.
