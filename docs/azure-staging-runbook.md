# Azure staging deployment runbook

## Preconditions

- GitHub environment `staging` has OIDC variables and protected deployment access.
- `POSTGRES_ADMIN_PASSWORD` and `REGIMPACT_JWT_SECRET` are environment secrets.
- The Azure subscription has sufficient quota in `canadacentral`.
- A cost budget and owner are confirmed before provisioning.
- The OIDC principal is scoped to `rg-regimpact-staging`, with Contributor and Role Based Access
  Control Administrator; it has no subscription-wide deployment role.

## Deploy

Dispatch `deploy-azure` for `staging` from a commit that passed every quality check. The workflow
uses immutable Git SHA image tags, reviews Bicep changes, provisions dependencies, runs migrations
before promotion, exercises end-to-end readiness, and retains a deployment evidence artifact.

## Acceptance

1. Confirm every workflow step passed and download `deployment-evidence-<sha>`.
2. Run `RESOURCE_GROUP=rg-regimpact-staging scripts/validate-azure-staging.sh` locally.
3. Sign in through the public web endpoint with an explicitly provisioned staging user.
4. Verify RBAC, change preview, evidence investigation, ingestion ledger, and workflow approval.
5. Confirm demo account selection is absent and `/api/auth/demo-status` reports disabled.
6. Query Container Apps console/system logs and Application Insights for the test request.
7. Confirm the evidence artifact contains ready revisions and a successful migration execution.
8. Record the image SHA, web URL, test time, reviewer, and outcome.

## Incident triage

Check the latest ready revision, migration job execution, system logs, console logs, Key Vault
references, managed-identity role assignments, PostgreSQL readiness, Redis TLS connectivity, and
Blob authorization. Never copy secret values into an issue or workflow summary.

## Rollback

Use a previously accepted Git SHA with `scripts/rollback-azure-staging.sh`. The script verifies both
images exist, updates API-derived workloads and web, and repeats smoke tests. Do not downgrade a
database schema automatically. For an incompatible migration, restore into a separate server and
follow an approved recovery plan.

## Teardown and cost control

Staging resources incur charges even when Container Apps scale to zero, especially PostgreSQL and
Redis. When the environment is no longer needed, export evidence and delete the staging resource
group only after confirming no shared resources or retained data depend on it.
