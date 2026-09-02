#!/usr/bin/env bash
set -euo pipefail

: "${RESOURCE_GROUP:=rg-regimpact-staging}"
: "${EXPECTED_VERSION:=0.5.0a1}"

deployment=$(az deployment group list \
  --resource-group "$RESOURCE_GROUP" \
  --query "sort_by([?properties.provisioningState=='Succeeded'], &properties.timestamp)[-1].name" \
  --output tsv)
[[ -n "$deployment" ]] || { echo "No successful deployment found" >&2; exit 1; }

outputs=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$deployment" \
  --query properties.outputs \
  --output json)
web_url=$(jq -r '.webUrl.value // empty' <<<"$outputs")
[[ -n "$web_url" ]] || { echo "Deployment does not expose webUrl" >&2; exit 1; }

apps=(api web worker dispatcher scheduler)
for component in "${apps[@]}"; do
  state=$(az containerapp show \
    --resource-group "$RESOURCE_GROUP" \
    --name "regimpact-staging-$component" \
    --query properties.provisioningState \
    --output tsv)
  [[ "$state" == "Succeeded" ]] || { echo "$component provisioning state: $state" >&2; exit 1; }
done

migration_job=$(jq -r '.migrationJobName.value // empty' <<<"$outputs")
[[ -n "$migration_job" ]] || { echo "Deployment does not expose migrationJobName" >&2; exit 1; }
migration_status=$(az containerapp job execution list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$migration_job" \
  --query "sort_by([], &properties.startTime)[-1].properties.status" \
  --output tsv)
[[ "$migration_status" == "Succeeded" ]] || {
  echo "Latest migration execution status: ${migration_status:-missing}" >&2
  exit 1
}

WEB_URL="$web_url" EXPECTED_VERSION="$EXPECTED_VERSION" scripts/smoke-test-azure.sh

apps_json=$(az containerapp list \
  --resource-group "$RESOURCE_GROUP" \
  --query "[?starts_with(name, 'regimpact-staging-')].{name:name,provisioning_state:properties.provisioningState,latest_revision:properties.latestRevisionName,latest_ready_revision:properties.latestReadyRevisionName}" \
  --output json)

jq -n \
  --arg checked_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg resource_group "$RESOURCE_GROUP" \
  --arg deployment "$deployment" \
  --arg web_url "$web_url" \
  --arg version "$EXPECTED_VERSION" \
  --arg migration_job "$migration_job" \
  --arg migration_status "$migration_status" \
  --argjson apps "$apps_json" \
  '{checked_at:$checked_at,resource_group:$resource_group,deployment:$deployment,web_url:$web_url,expected_version:$version,migration:{job:$migration_job,status:$migration_status},apps:$apps,status:"passed"}' \
  > deployment-evidence.json

echo "Azure staging operational validation passed."
