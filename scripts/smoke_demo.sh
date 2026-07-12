#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API_KEY="${API_KEY:-}"

HEADER_ARGS=()
if [[ -n "$API_KEY" ]]; then
  HEADER_ARGS=(-H "X-API-Key: $API_KEY")
fi

curl -fsS "$BASE_URL/api/v1/health/detail" >/dev/null
curl -fsS -X POST "${HEADER_ARGS[@]}" "$BASE_URL/api/v1/legal/wecom-archive/replay-demo" >/dev/null
curl -fsS "${HEADER_ARGS[@]}" "$BASE_URL/api/v1/legal/document-sync-logs?page_size=10&sync_target=kdocs" >/dev/null

echo "smoke demo passed: $BASE_URL"

