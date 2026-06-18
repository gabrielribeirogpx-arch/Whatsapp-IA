"""Run Alembic release migrations under a PostgreSQL advisory lock."""
from __future__ import annotations

import os
import subprocess
import psycopg2

# Stable 64-bit lock id reserved for Railway release migrations in this app.
ALEMBIC_RELEASE_LOCK_ID = 2026061801


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL not set")
    return database_url


def main() -> int:
    database_url = _database_url()
    print("[RELEASE] acquiring Alembic advisory lock", flush=True)
    with psycopg2.connect(database_url) as conn:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (ALEMBIC_RELEASE_LOCK_ID,))
            try:
                print("[RELEASE] Alembic advisory lock acquired", flush=True)
                subprocess.run(["alembic", "upgrade", "head"], check=True)
                print("[RELEASE] Alembic upgrade head completed", flush=True)
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (ALEMBIC_RELEASE_LOCK_ID,))
                print("[RELEASE] Alembic advisory lock released", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
