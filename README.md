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
| v0.3A | Database authentication and backend RBAC |
| v0.3B | Structured logging, metrics, tracing and operational dashboards |
| v0.3C | Azure deployment, CI/CD, secrets and infrastructure as code |
| v0.3D | Reliable ingestion retries, dead letters and monitoring |
| v0.4 | Controlled agentic impact workflows, evaluation, safety gates and human approval |
| v0.4 | Controlled agentic workflow, evaluation and human approval |
| v1.0 | AKS, Helm, autoscaling, rollback and recovery testing |

## Repository layout

```text
apps/api/          FastAPI application and domain services
apps/web/          Next.js analyst console
docs/              Architecture, product and design decisions
infra/             Cloud infrastructure (introduced in v0.5)
```

## Current milestone: v0.4 controlled agentic workflows

v0.4 introduces bounded regulatory-impact assessments. The agent collects versioned evidence,
proposes control impacts, and evaluates deterministic policy gates. It cannot execute downstream
changes. An authenticated administrator must approve, reject, or request changes, and every
decision is append-only and tenant scoped.

- Azure Container Apps deployment architecture expressed in Bicep
- Managed PostgreSQL, Redis, Blob Storage, ACR, Key Vault and Application Insights
- GitHub Actions deployment through OIDC without stored Azure client secrets
- Staging and protected production environments with immutable image tags
- Azure Blob object storage through managed identity

- Structured JSON logs with request, trace, tenant, and actor correlation
- W3C trace-context propagation and response correlation headers
- Prometheus-format request, latency, concurrency, and uptime metrics
- Separate startup, liveness, and dependency-aware readiness endpoints
- Administrator-only operational snapshot and dashboard

- Database-backed organization users with admin, analyst and viewer roles
- Memory-hard scrypt password hashing and short-lived signed access tokens
- Tenant and actor identity derived from validated tokens instead of browser headers
- Server-side HTTP-only authentication cookie and protected Next.js routes
- Role enforcement for analyst decisions and administrative configuration
- Successful-login audit events and inactive-user enforcement

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

Open `http://localhost:3000` and sign in with one of the local-only accounts configured in `docker-compose.yml`: `admin@northstar.local`, `analyst@northstar.local`, or `viewer@northstar.local`. The corresponding demonstration passwords must be replaced outside local development. The seed command is safe to run repeatedly and provisions the Northstar Energy reference tenant, role accounts, source history, obligations, controls, mappings, review decisions, monitored source, and ingestion ledger. The regulatory clauses are synthetic test fixtures and are not legal or regulatory advice.

For frontend-only development, set `REGIMPACT_API_BASE_URL=http://localhost:8000` and run `npm run dev` from `apps/web`.

See `docs/authentication-and-rbac.md` for the security boundary, permission matrix, configuration, and deliberately deferred identity-provider controls.

See `docs/observability.md` for telemetry contracts, probe semantics, metric-cardinality safeguards, and initial alert guidance.

See `docs/azure-deployment.md` for cloud architecture, GitHub environment setup, security boundaries, deployment flow, and cost controls.

The `development_allow` malware scanner is deliberately restricted to the local environment. Non-local environments fail closed until the production malware-scanning adapter is configured.

## Quality checks

Backend tests, linting, static typing, frontend linting, TypeScript validation, and the production web build are enforced in CI. For a local checkout with dependencies installed, run `make quality`.
