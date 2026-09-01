# Hybrid regulatory evidence retrieval

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
