#!/bin/bash
set -euo pipefail

echo "🚦 Running release migrations..."

if [ -z "${DATABASE_URL:-}" ]; then
  echo "❌ DATABASE_URL not set"
  exit 1
fi

python scripts/run_release_migrations.py
