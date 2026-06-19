#!/bin/bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -n "${RAILWAY_SERVICE_NAME:-}" ] && [ "${RAILWAY_SERVICE_NAME}" != "Backend" ] && [ "${RAILWAY_SERVICE_NAME}" != "Migration Service" ]; then
  echo "Skipping release migrations for Railway service: ${RAILWAY_SERVICE_NAME}"
  exit 0
fi

echo "🚦 Running release migrations..."

if [ -z "${DATABASE_URL:-}" ]; then
  echo "❌ DATABASE_URL not set"
  exit 1
fi

python scripts/run_release_migrations.py
