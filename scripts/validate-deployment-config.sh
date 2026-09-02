#!/usr/bin/env bash
set -euo pipefail

required_files=(
  infra/main.bicep
  infra/staging.bicepparam
  infra/production.bicepparam
  .github/workflows/deploy-azure.yml
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

if grep -R -nE 'AZURE_CLIENT_SECRET|password[[:space:]]*=[[:space:]]*[^$]' infra .github/workflows; then
  echo "Potential embedded deployment secret detected" >&2
  exit 1
fi

echo "Deployment configuration checks passed."
