#!/usr/bin/env bash
set -euo pipefail

pytest -q
alembic upgrade head
python -m app.cli check-config
echo "preflight passed"
