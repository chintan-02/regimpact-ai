# v0.5.0 release audit

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

Production deployment is not approved by this release. Private networking, enterprise malware scanning, Entra
workforce identity, restore drills, and Azure Managed Redis remain explicit production boundaries.

## Local verification

- API tests: 76 passed.
- Ruff: passed.
- mypy: passed for 40 source files.
- Web ESLint, TypeScript, and optimized Next.js build: passed.
- Shell syntax and deployment-policy checks: passed.
- Bicep compilation, infrastructure validation, PostgreSQL integration, API tests, and web build: passed in GitHub Actions.
- Authenticated Azure staging deployment, migrations, health verification, and evidence capture: passed.

## Azure staging verification

- Deployment workflow: `deploy-azure`
- Successful run: `33692643667`
- Deployment commit: `f87dae132cba5260045d04a8d603a350ff0d5883`
- Environment: protected GitHub `staging` environment with OIDC authentication
- Resource group: `rg-regimpact-staging`
- Azure region: `canadacentral`
- Promotion deployment: `promotion-33692643667`
- Migration job: `regimpact-staging-migrate` — succeeded
- Container Apps: API, web, worker, dispatcher, and scheduler — provisioning and latest revisions succeeded
- Public readiness: returned `{"status":"ready","version":"0.5.0a1"}`
- Protected operations route: redirected to `/login`
- Evidence timestamp: `2026-09-02T23:06:45Z`
- GitHub artifact: `deployment-evidence-f87dae132cba5260045d04a8d603a350ff0d5883`
- Local evidence copy: `regimpact-deployment-evidence-33692643667`
- Monthly staging budget: CA$20 with alerts
- Actual Azure cost: pending Cost Management ingestion at audit time

The deployment exposed and resolved Azure-specific compatibility issues involving OIDC subject matching, Log Analytics retention, Key Vault purge-protection semantics, OIDC token refresh, PostgreSQL pgvector allow-listing, and two-phase PostgreSQL configuration updates.
