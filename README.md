# RegImpact AI

Regulatory Change Impact and Controls Assurance Platform.

RegImpact monitors regulatory sources, versions incoming documents, detects section-level changes, classifies obligations, maps affected controls and evidence, and routes uncertain findings through human review.

## Product boundary

This is not a regulatory chatbot and it does not provide legal advice. It is an analyst workflow that preserves evidence, lineage, review decisions, and audit history.

## Release plan

| Release | Outcome |
| --- | --- |
| v0.1 | Versioned ingestion, deterministic change detection, citations |
| v0.2 | Obligation extraction, confidence calibration, hybrid retrieval, control mapping |
| v0.3 | Entra/OIDC authentication and backend RBAC |
| v0.4 | Fine-tuned obligation classifier and evaluation report |
| v0.5 | Azure deployment, CI/CD, infrastructure as code |
| v0.6 | Distributed tracing and operational/AI/business monitoring |
| v1.0 | AKS, Helm, autoscaling, rollback and recovery testing |

## Repository layout

```text
apps/api/          FastAPI application and domain services
apps/web/          Next.js analyst console
docs/              Architecture, product and design decisions
infra/             Cloud infrastructure (introduced in v0.5)
```

## Current milestone: v0.2E analyst workflow

- Immutable regulation/version domain model
- Normalized SHA-256 content identity
- Idempotent version ingestion
- Deterministic section-level added/modified/removed detection
- Stable API error contract and request IDs
- Health/readiness endpoints
- Unit tests for the core change engine
- Independent visual system for the analyst console
- Signature-verified PDF/HTML uploads with strict limits
- Durable, deduplicated ingestion jobs and content-addressed object storage
- Page-aware extraction, deterministic section parsing and failed-job audit state
- Transactional outbox, Redis/Dramatiq workers and dead-letter state
- Scheduled conditional source monitoring with SSRF-oriented URL controls
- Data-backed change register, source registry, ingestion ledger and clause-level evidence view
- Deterministic, idempotent demonstration dataset for recruiter and stakeholder walkthroughs
- Evidence-linked obligation candidates with versioned deterministic extraction
- Explainable confidence features and explicit human-review routing
- Idempotent extraction runs, including zero-candidate versions
- Tenant-scoped obligation APIs and frozen evaluation gates
- Versioned confidence policy with raw-score preservation
- Laplace-smoothed empirical calibration bins
- Precision-constrained human-review threshold selection
- Inspectable calibration-policy API and policy lineage on every obligation
- Immutable section search index with embedding-model lineage
- PostgreSQL full-text search and pgvector cosine retrieval
- Reciprocal-rank fusion with organization-scoped candidate queries
- Citation-complete hybrid-search API and idempotent indexing
- Organization-scoped, versioned control catalogue
- Evidence-linked obligation-to-control mapping candidates
- Explicit suggested, needs-review, ambiguous and unmapped states
- Obligation register and control catalogue analyst workspaces
- Tenant-isolated control and mapping read models
- Append-only accepted, rejected, deferred, and confirmed-unmapped decisions
- Mandatory rationale, development actor lineage, idempotency, and stale-update protection
- Tenant-scoped, paginated review queue with evidence and candidate comparison
- Obligation and control detail workspaces with operational decision states
- Separate mapping evaluation for recall/precision at top-k, MRR, coverage, ambiguity, unmapped detection, and review workload
- Eight-case curated mapping fixture with explicit engineering-only limitations

## Local backend setup

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn regimpact.main:app --reload
python -m unittest discover -s tests -v
```

The deterministic domain tests keep an in-memory adapter for speed. The HTTP application uses the organization-scoped SQLAlchemy repository and PostgreSQL schema.

## Run the complete local stack

```bash
docker compose up -d --build
docker compose --profile demo run --rm seed
```

Open `http://localhost:3000`. The seed command is safe to run repeatedly and provisions the Northstar Energy reference tenant with two source versions, three latest-version changes, three evidence-linked obligation candidates, three versioned controls, mapping candidates, representative accepted/rejected/deferred review decisions, one monitored AER publication source, and a completed ingestion ledger. Confirmed-unmapped is supported but is not seeded because every reference obligation has a candidate. The regulatory clauses are synthetic test fixtures and are not legal or regulatory advice.

For frontend-only development, set `REGIMPACT_API_BASE_URL=http://localhost:8000` and run `npm run dev` from `apps/web`.

Until Entra/OIDC lands in v0.3, API calls use explicit `X-Organization-ID` and `X-Actor-ID` development headers. They are not authentication and must never be enabled as a production identity mechanism.

The `development_allow` malware scanner is deliberately restricted to the local environment. Non-local environments fail closed until the production malware-scanning adapter is configured.

## Quality checks

Backend tests, linting, static typing, frontend linting, TypeScript validation, and the production web build are enforced in CI. For a local checkout with dependencies installed, run `make quality`.
