# Azure deployment and CI/CD

RegImpact AI v0.5 targets Azure Container Apps in `canadacentral`. Bicep is the source of truth
for staging and production; GitHub Actions builds immutable images and authenticates with workload
identity federation rather than a client secret.

## Deployed topology

- Azure Container Registry with the admin account disabled;
- one Container Apps environment connected to Log Analytics;
- public Next.js web ingress and internal-only FastAPI ingress;
- API and worker Container Apps using one user-assigned managed identity;
- scheduled Container Apps jobs for the transactional-outbox dispatcher and regulatory-source scheduler;
- a manual Container Apps migration job;
- PostgreSQL Flexible Server 17, Azure Cache for Redis, and Azure Blob Storage;
- Key Vault secret references for database, Redis, and JWT values;
- Application Insights backed by Log Analytics;
- managed-identity roles limited to ACR pull, Blob data contribution, and Key Vault secret reads.

The API and `/metrics` endpoint are not internet-accessible. The web application performs
server-side API calls inside the Container Apps environment.

## GitHub environment configuration

Create a protected GitHub environment named `staging`. Add these environment variables:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

Add these environment secrets:

- `POSTGRES_ADMIN_PASSWORD`
- `REGIMPACT_JWT_SECRET` (at least 32 random characters)

Run `scripts/bootstrap-azure-oidc.sh` once from an authenticated administrative workstation to
create the staging resource group and federated credential. The deployer receives Contributor and
Role Based Access Control Administrator only on `rg-regimpact-staging`; it receives no
subscription-wide deployment role. Review both assignments against organization policy before use.

## Deployment sequence

The manually dispatched workflow validates Bicep, reviews the Azure what-if result, provisions
foundation resources, builds and pushes SHA-tagged images, deploys workloads at zero replicas,
runs Alembic as a one-shot job, promotes the migrated workloads, and verifies the complete public
web to internal API to PostgreSQL/Redis readiness path. The dispatcher and scheduler are bounded
scheduled jobs rather than idle 24/7 containers. Concurrency controls serialize deployments per
environment. A JSON evidence artifact records the successful deployment and tested version. Unless
`keep_staging_online=true` is explicitly selected, the workflow then captures a pre-delete resource
inventory and requests deletion of the complete staging resource group.

No deployment occurs from pull requests. CI compiles Bicep and runs the existing backend,
PostgreSQL, frontend, lint, type, and test gates first.

The v0.5 workflow intentionally exposes only `staging`. Production deployment remains disabled
until the staging evidence is accepted and the production boundary below is resolved.

## Known production boundary

This portfolio release uses Azure service firewalls and TLS for PostgreSQL and Redis so it can be
deployed without custom DNS administration. A regulated production tenant should add private
endpoints, private DNS zones, a delegated VNet, Web Application Firewall, DDoS policy, enterprise
malware scanning, Entra workforce authentication, backup-restore drills, and organization-specific
retention policies before go-live. The application deliberately fails closed for document ingestion
when a production malware scanner is not configured.

## Cost control

The staging environment is intentionally **ephemeral**. A normal deployment provisions the complete
production-shaped topology, validates it, uploads deployment evidence, captures a final resource
inventory, and deletes `rg-regimpact-staging`. Keeping staging online is an explicit opt-in action
because managed PostgreSQL, Redis, Container Registry, Application Insights/Log Analytics, and
Container Apps can all accrue cost while the environment exists.

The cost profile is deliberately bounded while preserving architectural evidence:

- PostgreSQL staging remains on the Burstable `Standard_B1ms` tier with 32 GiB storage, seven-day
  backups, no geo-redundant backup, and no high availability. The database is deleted with the
  ephemeral staging resource group instead of being left idle.
- Redis remains Basic C0 only for short-lived staging because Dramatiq currently depends on Redis.
  It is not treated as a permanent low-cost service. Azure Cache for Redis is also on Microsoft's
  retirement path, so a long-lived production environment must migrate to a supported Redis
  offering rather than creating a new dependency on the retiring service.
- The dispatcher is a bounded one-shot Container Apps Job scheduled every minute. The scheduler is
  a one-shot Container Apps Job scheduled every 15 minutes, matching the API's minimum source poll
  interval. Both retain long-running loop modes locally for Docker Compose development.
- Container console/system log streaming to Log Analytics is disabled in ephemeral staging to avoid
  high-volume ingestion. Application Insights remains available for application telemetry and the
  production parameter keeps container logging enabled.
- Basic ACR, locally redundant Blob Storage, and Key Vault remain because they are inexpensive
  compared with the always-on compute/data services and preserve the real Azure delivery pattern.

The Next.js frontend intentionally remains a Container App rather than static hosting. It performs
server-side calls to an internal-only FastAPI endpoint, so converting it to a static site would
either break the current runtime model or require exposing/re-architecting the API security
boundary. That would be a larger product architecture change, not a cost-only optimization.

Always run `az deployment group what-if` and review the Azure pricing estimate before deploying.
For portfolio validation, prefer the default temporary lifecycle and never leave staging online
without a time-bounded reason.

## Operational validation and rollback

After a staging deployment, run `scripts/validate-azure-staging.sh`. It verifies the provisioning
state of the API, web, and worker Container Apps plus the migration, dispatcher, and scheduler jobs;
it exercises the public readiness proxy, confirms the deployed API version, and proves demo access
is disabled. Preserve `deployment-evidence.json` with the release.

Rollback uses immutable Git SHA image tags. Set `REGISTRY_NAME`, `KNOWN_GOOD_TAG`, and
`CONFIRM_ROLLBACK=staging`, then run `scripts/rollback-azure-staging.sh`. Database downgrades are not
automatic: only roll application images back when the corresponding schema is backward compatible.

For local compilation only, export non-production placeholder values before compiling parameter
files. Compilation does not contact Azure or store these values in the generated template:

```bash
export POSTGRES_ADMIN_PASSWORD='CompileOnly-NotForDeployment-2026!'
export REGIMPACT_JWT_SECRET='compile-only-placeholder-at-least-32-characters'
az bicep build-params --file infra/staging.bicepparam --outfile /tmp/staging.json
unset POSTGRES_ADMIN_PASSWORD REGIMPACT_JWT_SECRET
```
