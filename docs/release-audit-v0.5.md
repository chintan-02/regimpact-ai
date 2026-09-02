# v0.5 alpha release audit

Scope: real Azure staging deployment validation, end-to-end readiness, controlled migrations,
immutable deployment evidence, rollback tooling, observability wiring, and cost-aware operations.

The public readiness route exposes only generic status and version while proving that Next.js can
reach the internal API and that the API can reach PostgreSQL and Redis. Azure staging keeps demo
authentication disabled. Application and worker environments receive the Application Insights
connection string; Container Apps continues to ship console and system logs to Log Analytics.

Acceptance requires Bicep and parameter compilation, deployment-policy validation, full Python
quality checks, frontend lint/type/build checks, Docker regression testing, an authenticated Azure
OIDC deployment, successful migration execution, healthy Container Apps, smoke tests, retained
deployment evidence, and a reviewed rollback procedure.

Production is not approved by this alpha. Private networking, enterprise malware scanning, Entra
workforce identity, restore drills, and Azure Managed Redis remain explicit production boundaries.

## Local verification

- API tests: 76 passed.
- Ruff: passed.
- mypy: passed for 40 source files.
- Web ESLint, TypeScript, and optimized Next.js build: passed.
- Shell syntax and deployment-policy checks: passed.
- Bicep compilation and Docker regression: delegated to CI because this review environment does
  not provide Azure CLI/Bicep or Docker.
- Authenticated staging deployment and operational evidence: required before this alpha can be
  accepted or finalized.
