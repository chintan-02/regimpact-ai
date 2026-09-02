#!/usr/bin/env bash
set -euo pipefail

required_files=(
  infra/main.bicep
  infra/staging.bicepparam
  infra/production.bicepparam
  .github/workflows/deploy-azure.yml
  scripts/smoke-test-azure.sh
  scripts/validate-azure-staging.sh
  scripts/rollback-azure-staging.sh
  scripts/bootstrap-azure-oidc.sh
)
for required_file in "${required_files[@]}"; do
  test -s "$required_file" || { echo "Missing $required_file" >&2; exit 1; }
done

grep -q "id-token: write" .github/workflows/deploy-azure.yml
grep -q "azure/login@v2" .github/workflows/deploy-azure.yml
grep -q "@secure()" infra/main.bicep
grep -q "enableRbacAuthorization: true" infra/main.bicep
grep -q "adminUserEnabled: false" infra/main.bicep
grep -q "allowBlobPublicAccess: false" infra/main.bicep
grep -q "external: false, targetPort: 8000" infra/main.bicep
grep -q "APPLICATIONINSIGHTS_CONNECTION_STRING" infra/main.bicep
grep -q "/api/platform/readiness" infra/main.bicep
grep -q "deployment-evidence" .github/workflows/deploy-azure.yml
grep -q 'options: \[staging\]' .github/workflows/deploy-azure.yml
grep -q 'resourceGroups/${resource_group}' scripts/bootstrap-azure-oidc.sh
grep -q 'Role Based Access Control Administrator' scripts/bootstrap-azure-oidc.sh

if grep -q 'options: \[staging, production\]' .github/workflows/deploy-azure.yml; then
  echo "Production deployment must remain disabled for v0.5.0" >&2
  exit 1
fi

if grep -R -nE 'AZURE_CLIENT_SECRET|password[[:space:]]*=[[:space:]]*[^$]' infra .github/workflows; then
  echo "Potential embedded deployment secret detected" >&2
  exit 1
fi

echo "Deployment configuration checks passed."
