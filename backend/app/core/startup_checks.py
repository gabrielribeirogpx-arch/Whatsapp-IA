from __future__ import annotations

import importlib.util
import logging
import os
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

logger = logging.getLogger(__name__)

PRODUCTION_ENV_NAMES = {"production", "prod"}
REQUIRED_DEPENDENCIES = ("alembic", "sqlalchemy", "fastapi", "argon2")
WORKER_REQUIRED_DEPENDENCIES = ("alembic", "sqlalchemy", "redis", "rq", "argon2")
WEAK_PRODUCTION_SECRETS = {"", "wazza-dev-secret", "changeme", "change-me", "secret", "dev-secret"}


def is_production() -> bool:
    return (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("ENVIRONMENT") or "").strip().lower() in PRODUCTION_ENV_NAMES


def _repo_backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    backend_dir = _repo_backend_dir()
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def should_run_migrations_on_start() -> bool:
    """Opt-in escape hatch for local/dev startup only.

    Production deploys must run Alembic in a single release/deploy step and keep
    web/worker processes as schema validators only, avoiding rolling deploy races.
    """
    return _env_flag("RUN_MIGRATIONS_ON_START", default=False) or _env_flag("RUN_MIGRATIONS", default=False)


def wait_for_database(*, attempts: int = 10, delay_seconds: float = 2.0) -> None:
    from app.db.session import engine

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("event=db_ready attempt=%s", attempt)
            return
        except Exception as exc:
            last_error = exc
            logger.warning("event=db_wait_retry attempt=%s error=%s", attempt, type(exc).__name__)
            if attempt < attempts:
                time.sleep(delay_seconds)
    raise RuntimeError("Database is not reachable") from last_error


def verify_required_dependencies(required: tuple[str, ...] = REQUIRED_DEPENDENCIES) -> None:
    missing = [package for package in required if importlib.util.find_spec(package) is None]
    if missing:
        raise RuntimeError(f"Missing required dependencies: {', '.join(missing)}")


def _require_strong_secret(name: str) -> None:
    value = (os.getenv(name) or "").strip()
    if is_production() and (len(value) < 32 or value.lower() in WEAK_PRODUCTION_SECRETS):
        raise RuntimeError(f"{name} must be set to a strong value (>=32 chars) in production")


def verify_runtime_secrets() -> None:
    _require_strong_secret("AUTH_SECRET")
    _require_strong_secret("PASSWORD_RESET_SECRET")


def run_migrations_if_enabled() -> None:
    if not should_run_migrations_on_start():
        logger.info("event=migrations_on_start_skipped")
        return
    if is_production():
        raise RuntimeError("RUN_MIGRATIONS_ON_START/RUN_MIGRATIONS must stay disabled in production; run Alembic in the release step")
    command.upgrade(alembic_config(), "head")
    logger.info("event=migrations_applied_on_start")


def verify_alembic_at_head() -> None:
    cfg = alembic_config()
    script = ScriptDirectory.from_config(cfg)
    expected_heads = set(script.get_heads())
    from app.db.session import engine

    with engine.connect() as connection:
        current_heads = set(MigrationContext.configure(connection).get_current_heads())
    if current_heads != expected_heads:
        raise RuntimeError(
            "Database migrations are not at Alembic head; run `alembic upgrade head` in the release/deploy step "
            f"before starting services. current={sorted(current_heads)} expected={sorted(expected_heads)}"
        )
    logger.info("event=alembic_head_verified heads=%s", sorted(current_heads))


def verify_required_env_vars(*names: str) -> None:
    missing = [name for name in names if not (os.getenv(name) or "").strip()]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
