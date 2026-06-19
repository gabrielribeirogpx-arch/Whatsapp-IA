"""Dedicated Railway entrypoint for one-shot Alembic release migrations.

This module intentionally does not import or start FastAPI, workers, Redis
consumers, or any queue processing. It delegates to the existing release script
so migration behavior stays centralized in backend/release.sh and
backend/scripts/run_release_migrations.py.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("migration-service")


def _backend_dir() -> Path:
    return Path(__file__).resolve().parent


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger.info("event=migration_service_started")
    try:
        subprocess.run(["bash", "release.sh"], cwd=_backend_dir(), check=True)
    except Exception:
        logger.exception("event=migration_service_failed")
        return 1
    logger.info("event=migration_service_completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
