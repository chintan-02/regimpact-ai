#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID}"
: "${GITHUB_ORG:?Set GITHUB_ORG}"
: "${GITHUB_REPO:?Set GITHUB_REPO}"

application_name="regimpact-github-deployer"
application_id=$(az ad app create --display-name "$application_name" --query appId -o tsv)
principal_id=$(az ad sp create --id "$application_id" --query id -o tsv)
scope="/subscriptions/${AZURE_SUBSCRIPTION_ID}"

az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "$scope"

for deployment_environment in staging production; do
  credential_file=$(mktemp)
  trap 'rm -f "$credential_file"' EXIT
  printf '%s\n' \
    '{' \
    "  \"name\": \"github-${deployment_environment}\"," \
    "  \"issuer\": \"https://token.actions.githubusercontent.com\"," \
    "  \"subject\": \"repo:${GITHUB_ORG}/${GITHUB_REPO}:environment:${deployment_environment}\"," \
    '  "audiences": ["api://AzureADTokenExchange"]' \
    '}' > "$credential_file"
  az ad app federated-credential create --id "$application_id" --parameters "$credential_file"
  rm -f "$credential_file"
  trap - EXIT
done

printf 'AZURE_CLIENT_ID=%s\n' "$application_id"
printf 'AZURE_TENANT_ID=%s\n' "$(az account show --query tenantId -o tsv)"
printf 'AZURE_SUBSCRIPTION_ID=%s\n' "$AZURE_SUBSCRIPTION_ID"
