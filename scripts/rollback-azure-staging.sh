#!/usr/bin/env bash
set -euo pipefail

: "${RESOURCE_GROUP:=rg-regimpact-staging}"
: "${REGISTRY_NAME:?Set REGISTRY_NAME}"
: "${KNOWN_GOOD_TAG:?Set KNOWN_GOOD_TAG to an immutable Git SHA}"
: "${CONFIRM_ROLLBACK:?Set CONFIRM_ROLLBACK=staging}"
[[ "$CONFIRM_ROLLBACK" == "staging" ]] || { echo "Rollback confirmation must equal staging" >&2; exit 1; }
[[ "$KNOWN_GOOD_TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "KNOWN_GOOD_TAG must be a 40-character Git SHA" >&2; exit 1; }

az acr repository show --name "$REGISTRY_NAME" --image "regimpact-api:$KNOWN_GOOD_TAG" >/dev/null
az acr repository show --name "$REGISTRY_NAME" --image "regimpact-web:$KNOWN_GOOD_TAG" >/dev/null

api_image="$REGISTRY_NAME.azurecr.io/regimpact-api:$KNOWN_GOOD_TAG"
web_image="$REGISTRY_NAME.azurecr.io/regimpact-web:$KNOWN_GOOD_TAG"
for component in api worker dispatcher scheduler; do
  az containerapp update \
    --resource-group "$RESOURCE_GROUP" \
    --name "regimpact-staging-$component" \
    --image "$api_image" \
    --output none
done
az containerapp update \
  --resource-group "$RESOURCE_GROUP" \
  --name regimpact-staging-web \
  --image "$web_image" \
  --output none

web_url="https://$(az containerapp show --resource-group "$RESOURCE_GROUP" --name regimpact-staging-web --query properties.configuration.ingress.fqdn --output tsv)"
WEB_URL="$web_url" scripts/smoke-test-azure.sh
echo "Staging rollback completed with immutable tag $KNOWN_GOOD_TAG."
