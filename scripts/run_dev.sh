#!/usr/bin/env bash
set -euo pipefail

mkdir -p storage
uvicorn app.main:app --reload
