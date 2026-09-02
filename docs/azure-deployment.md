# Azure deployment and CI/CD

RegImpact AI v0.3C targets Azure Container Apps in `canadacentral`. Bicep is the source of truth
for staging and production; GitHub Actions builds immutable images and authenticates with workload
identity federation rather than a client secret.

## Deployed topology

- Azure Container Registry with the admin account disabled;
- one Container Apps environment connected to Log Analytics;
- public Next.js web ingress and internal-only FastAPI ingress;
- API, worker, dispatcher, and scheduler workloads using one user-assigned managed identity;
- a manual Container Apps migration job;
- PostgreSQL Flexible Server 17, Azure Cache for Redis, and Azure Blob Storage;
- Key Vault secret references for database, Redis, and JWT values;
- Application Insights backed by Log Analytics;
- managed-identity roles limited to ACR pull, Blob data contribution, and Key Vault secret reads.

The API and `/metrics` endpoint are not internet-accessible. The web application performs
server-side API calls inside the Container Apps environment.

## GitHub environment configuration

Create protected GitHub environments named `staging` and `production`. Require manual approval for
production. Add these environment variables:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

Add these environment secrets:

- `POSTGRES_ADMIN_PASSWORD`
- `REGIMPACT_JWT_SECRET` (at least 32 random characters)

Run `scripts/bootstrap-azure-oidc.sh` once from an authenticated administrative workstation to
create the federated credentials. Review the subscription-scoped Contributor assignment and reduce
it to organization-approved custom roles before a real production launch.

## Deployment sequence

The manually dispatched workflow validates Bicep, provisions foundation resources, builds and
pushes SHA-tagged images, deploys workloads, runs Alembic as a one-shot job, waits for completion,
and verifies the public login page. Concurrency controls serialize deployments per environment.

No deployment occurs from pull requests. CI compiles Bicep and runs the existing backend,
PostgreSQL, frontend, lint, type, and test gates first.

## Known production boundary

This portfolio release uses Azure service firewalls and TLS for PostgreSQL and Redis so it can be
deployed without custom DNS administration. A regulated production tenant should add private
endpoints, private DNS zones, a delegated VNet, Web Application Firewall, DDoS policy, enterprise
malware scanning, Entra workforce authentication, backup-restore drills, and organization-specific
retention policies before go-live. The application deliberately fails closed for document ingestion
when a production malware scanner is not configured.

## Cost control

Staging uses burstable PostgreSQL, Basic Redis, Basic ACR, locally redundant Blob Storage, and a
maximum of two API/worker replicas. Production increases database availability, backup retention,
storage redundancy, and application scale. Always run `az deployment group what-if` and review the
Azure pricing estimate before deploying.

For local compilation only, export non-production placeholder values before compiling parameter
files. Compilation does not contact Azure or store these values in the generated template:

```bash
export POSTGRES_ADMIN_PASSWORD='CompileOnly-NotForDeployment-2026!'
export REGIMPACT_JWT_SECRET='compile-only-placeholder-at-least-32-characters'
az bicep build-params --file infra/staging.bicepparam --outfile /tmp/staging.json
unset POSTGRES_ADMIN_PASSWORD REGIMPACT_JWT_SECRET
```
