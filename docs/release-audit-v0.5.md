# v0.5.0 release audit

Scope: real Azure staging deployment validation, end-to-end readiness, controlled migrations,
immutable deployment evidence, rollback tooling, observability wiring, and cost-aware operations.

The public readiness route exposes only generic status and version while proving that Next.js can
reach the internal API and that the API can reach PostgreSQL and Redis. Azure staging keeps demo
authentication disabled. Application and worker environments receive the Application Insights
connection string; Container Apps continues to ship console and system logs to Log Analytics.

Acceptance required Bicep and parameter compilation, deployment-policy validation, full Python
quality checks, frontend lint/type/build checks, Docker regression testing, an authenticated Azure
OIDC deployment, successful migration execution, healthy Container Apps, smoke tests, retained
deployment evidence, and a reviewed rollback procedure.

Production deployment is not approved by this release. Private networking, enterprise malware
scanning, Entra workforce identity, restore drills, and Azure Managed Redis remain explicit
production boundaries.

## Verification summary

- API tests: 76 passed.
- Ruff: passed.
- mypy: passed for 40 source files.
- Web ESLint, TypeScript, and optimized Next.js build: passed.
- Shell syntax and deployment-policy checks: passed.
- Bicep compilation, infrastructure validation, PostgreSQL integration, API tests, and web build:
  passed in GitHub Actions.
- Authenticated Azure staging deployment, migrations, health verification, and evidence capture:
  passed.

## Final Azure staging evidence

| Field | Verified value |
| --- | --- |
| Workflow | `deploy-azure` |
| Successful run | [`33695340705`](https://github.com/chintan-02/regimpact-ai/actions/runs/33695340705) |
| Deployment commit | [`3b3d90ade4b75c845395a390b00cd3d0ba20d1d0`](https://github.com/chintan-02/regimpact-ai/commit/3b3d90ade4b75c845395a390b00cd3d0ba20d1d0) |
| Released version | `0.5.0` |
| GitHub environment | Protected `staging` environment with OIDC authentication |
| Azure resource group | `rg-regimpact-staging` |
| Azure region | `canadacentral` |
| Promotion deployment | `promotion-33695340705` |
| Migration job | `regimpact-staging-migrate` — `Succeeded` |
| Container Apps | API, web, worker, dispatcher, and scheduler — provisioning and latest revisions succeeded |
| Public readiness | `{"status":"ready","version":"0.5.0"}` |
| Protected operations route | Redirected to `/login` |
| Evidence artifact | `deployment-evidence-3b3d90ade4b75c845395a390b00cd3d0ba20d1d0` |
| Artifact created | `2026-09-02T23:41:37Z` |
| Local evidence copy | `regimpact-deployment-evidence-33695340705/deployment-evidence.json` |
| Monthly staging budget | CA$20 with alerts |
| Actual Azure cost | Pending Cost Management ingestion at audit time |

The deployment run completed every controlled stage: infrastructure provisioning, OIDC refresh,
immutable image publishing, zero-replica workload staging, database migration, workload promotion,
health verification, evidence capture, artifact upload, and deployment summary publication.

## Engineering lessons from deployment

The final release was reached by diagnosing several independent Azure integration failures rather
than treating deployment as a single opaque step:

1. Log Analytics rejected the original staging retention value, so the workspace was aligned to the
   supported SKU and retention contract.
2. Key Vault purge protection cannot be reverted from enabled to disabled, so non-production
   deployments omit the property instead of explicitly writing `false`.
3. A long infrastructure deployment exhausted the original OIDC token lifetime before ACR login, so
   the workflow refreshes its Azure session immediately before registry operations.
4. PostgreSQL Flexible Server requires the `VECTOR` extension to be allow-listed before Alembic can
   create pgvector objects.
5. Reapplying the PostgreSQL configuration during workload promotion caused a
   `ServerIsBusy` collision, so the two-phase deployment applies the extension configuration only
   during the foundation phase.

These corrections are captured in infrastructure and workflow code, making the successful result
repeatable rather than a one-off manual deployment.

## Evidence integrity

The GitHub artifact name includes the exact deployed commit. The readiness response reports the
final release version, and the annotated `v0.5.0` tag resolves to the same commit:

```text
release:  v0.5.0
commit:   3b3d90ade4b75c845395a390b00cd3d0ba20d1d0
run:      33695340705
version:  0.5.0
status:   ready
```
