#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID}"
: "${GITHUB_ORG:?Set GITHUB_ORG}"
: "${GITHUB_REPO:?Set GITHUB_REPO}"
: "${AZURE_LOCATION:=canadacentral}"

application_name="regimpact-github-deployer"
application_id=$(az ad app create --display-name "$application_name" --query appId -o tsv)
principal_id=$(az ad sp create --id "$application_id" --query id -o tsv)
resource_group="rg-regimpact-staging"
scope="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${resource_group}"

az group create \
  --name "$resource_group" \
  --location "$AZURE_LOCATION" \
  --tags application=regimpact-ai environment=staging managedBy=bicep \
  --output none

az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "$scope"

az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "Role Based Access Control Administrator" \
  --scope "$scope"

credential_file=$(mktemp)
trap 'rm -f "$credential_file"' EXIT
printf '%s\n' \
  '{' \
  '  "name": "github-staging",' \
  '  "issuer": "https://token.actions.githubusercontent.com",' \
  "  \"subject\": \"repo:${GITHUB_ORG}/${GITHUB_REPO}:environment:staging\"," \
  '  "audiences": ["api://AzureADTokenExchange"]' \
  '}' > "$credential_file"
az ad app federated-credential create --id "$application_id" --parameters "$credential_file"

printf 'AZURE_CLIENT_ID=%s\n' "$application_id"
printf 'AZURE_TENANT_ID=%s\n' "$(az account show --query tenantId -o tsv)"
printf 'AZURE_SUBSCRIPTION_ID=%s\n' "$AZURE_SUBSCRIPTION_ID"
printf 'AZURE_RESOURCE_GROUP=%s\n' "$resource_group"
