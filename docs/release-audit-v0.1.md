# v0.1 release audit

Audit date: 2026-08-31

## Scope

The Step 2D archive was extracted into an isolated workspace and checked as the v0.1 release candidate before v0.2 development.

## Corrections

- Replaced the removed `next lint` command with ESLint's supported CLI.
- Added the Next.js Core Web Vitals and TypeScript lint configuration.
- Added an explicit frontend TypeScript check.
- Enforced backend MyPy, frontend lint, and frontend type checking in CI.
- Added local `make quality` orchestration for all backend and frontend gates.

## Verification evidence

- Archive integrity: passed.
- Backend tests: 25 passed under pytest and unittest.
- Backend Ruff: passed.
- Backend MyPy: passed for 22 source files.
- Python dependency consistency: passed.
- Frontend ESLint: passed with zero warnings.
- Frontend TypeScript: passed.
- Next.js optimized production build: passed.
- Frontend production dependency audit: zero known vulnerabilities.
- PostgreSQL upgrade and downgrade SQL generation: passed for all three migrations.
- SQLite migration upgrade, downgrade, and re-upgrade smoke test: passed.
- Demo seed executed twice without duplicate regulations, versions, sources, or ingestion jobs.

The demo database contains three baseline `added` change records for version 1 and three latest-version changes for version 2. The product's latest-change API intentionally returns the three v1-to-v2 changes.

## Environment limitation

Docker is not installed in the audit workspace. Compose services and Dockerfiles were reviewed, but PostgreSQL/Redis/API/worker/web containers were not launched here. The PostgreSQL integration workflow remains the runtime verification gate in CI or on a Docker-enabled development machine.

## Accepted milestone boundaries

- Development organization and actor headers remain local-only until v0.3 OIDC/RBAC.
- Production malware scanning and cloud object storage are later deployment concerns; non-local scanning fails closed.
- v0.2 begins from this checkpoint with obligation extraction, confidence scoring, hybrid retrieval, and control mapping.
