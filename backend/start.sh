#!/bin/bash

echo "🚀 Starting app..."

if [ -z "$DATABASE_URL" ]; then
  echo "❌ DATABASE_URL not set"
  exit 1
fi

echo "⏳ Waiting for DB..."

python - << END
import time, os
from sqlalchemy import create_engine

db_url = os.getenv("DATABASE_URL")

for i in range(10):
    try:
        engine = create_engine(db_url)
        conn = engine.connect()
        conn.close()
        print("✅ DB OK")
        break
    except Exception as e:
        print("Retry DB...", e)
        time.sleep(2)
else:
    raise Exception("❌ DB not reachable")
END

echo "📦 Running migrations..."
alembic upgrade head

echo "🔥 Starting API..."
uvicorn app.main:app --host 0.0.0.0 --port $PORT
