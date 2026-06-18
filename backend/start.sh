#!/bin/bash
set -euo pipefail

echo "🚀 Starting app..."

if [ -z "${DATABASE_URL:-}" ]; then
  echo "❌ DATABASE_URL not set"
  exit 1
fi

if [ -z "${PORT:-}" ]; then
  echo "❌ PORT not set"
  exit 1
fi

echo "⏳ Verifying database and Alembic schema head..."
python - <<'PY'
from app.core.startup_checks import wait_for_database, verify_alembic_at_head

wait_for_database()
verify_alembic_at_head()
print("✅ DB reachable and Alembic is at head")
PY

echo "🔥 Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
