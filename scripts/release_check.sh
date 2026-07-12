#!/usr/bin/env bash
set -euo pipefail

RUN_TESTS="${RUN_TESTS:-true}"
RUN_ALEMBIC="${RUN_ALEMBIC:-true}"
RUN_DOCKER_BUILD="${RUN_DOCKER_BUILD:-false}"
LIVE_BASE_URL="${LIVE_BASE_URL:-}"

echo "== syntax checks =="
bash -n scripts/preflight.sh
bash -n scripts/smoke_demo.sh
bash -n scripts/release_check.sh
python3 -m py_compile scripts/acceptance_ocr_samples.py scripts/acceptance_wecom_sidecar_mock.py
python3 -m compileall -q app wecom_archive_sidecar

echo "== sensitive tracked files check =="
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  tracked_sensitive="$(git ls-files | grep -E '(^|/)(\.env($|\.)|.*\.pem$|.*\.key$|private_key.*|public_key.*|.*\.db$|.*\.sqlite3?$|wecom_archive_seq\.txt$)' | grep -v '^\.env\.example$' || true)"
  if [[ -n "$tracked_sensitive" ]]; then
    echo "release check failed: sensitive/runtime files are tracked:"
    echo "$tracked_sensitive"
    exit 1
  fi
fi

if [[ "$RUN_TESTS" == "true" ]]; then
  echo "== pytest =="
  pytest -q
fi

if [[ "$RUN_ALEMBIC" == "true" ]]; then
  echo "== alembic =="
  alembic upgrade head
fi

echo "== config =="
python3 -m app.cli check-config

if [[ -n "$LIVE_BASE_URL" ]]; then
  echo "== live smoke =="
  BASE_URL="$LIVE_BASE_URL" scripts/smoke_demo.sh
  BASE_URL="$LIVE_BASE_URL" python3 scripts/acceptance_ocr_samples.py
fi

if [[ "$RUN_DOCKER_BUILD" == "true" ]]; then
  echo "== docker build =="
  docker build -t legal-wecom-automation:release-check .
fi

echo "release check passed"
