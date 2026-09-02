#!/usr/bin/env bash
set -euo pipefail

: "${WEB_URL:?Set WEB_URL to the public staging URL}"
expected_version="${EXPECTED_VERSION:-}"
base_url="${WEB_URL%/}"
response_file=$(mktemp)
trap 'rm -f "$response_file"' EXIT

retry() {
  local url="$1"
  for _attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 15 "$url" > "$response_file"; then
      return 0
    fi
    sleep 10
  done
  return 1
}

retry "$base_url/login"
retry "$base_url/api/platform/readiness"
jq -e '.status == "ready"' "$response_file" >/dev/null
if [[ -n "$expected_version" ]]; then
  jq -e --arg version "$expected_version" '.version == $version' "$response_file" >/dev/null
fi

demo_status=$(curl --fail --silent --show-error --max-time 15 "$base_url/api/auth/demo-status")
jq -e '.enabled == false' <<<"$demo_status" >/dev/null
printf 'Azure staging smoke tests passed for %s\n' "$base_url"
