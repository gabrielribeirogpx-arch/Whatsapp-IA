from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# Keep these focused unit tests independent from the host Python/Alembic/SQLAlchemy
# installation while still exercising this repository's migration orchestration.
alembic_module = types.ModuleType("alembic")
alembic_module.command = types.SimpleNamespace(upgrade=lambda *_args, **_kwargs: None)
alembic_config_module = types.ModuleType("alembic.config")
alembic_config_module.Config = lambda *_args, **_kwargs: types.SimpleNamespace(set_main_option=lambda *_a, **_k: None)
alembic_runtime_module = types.ModuleType("alembic.runtime")
alembic_migration_module = types.ModuleType("alembic.runtime.migration")
alembic_migration_module.MigrationContext = types.SimpleNamespace(configure=lambda _conn: None)
alembic_script_module = types.ModuleType("alembic.script")
alembic_script_module.ScriptDirectory = types.SimpleNamespace(from_config=lambda _cfg: None)
sqlalchemy_module = types.ModuleType("sqlalchemy")
sqlalchemy_module.text = lambda sql: sql
sys.modules.setdefault("alembic", alembic_module)
sys.modules.setdefault("alembic.config", alembic_config_module)
sys.modules.setdefault("alembic.runtime", alembic_runtime_module)
sys.modules.setdefault("alembic.runtime.migration", alembic_migration_module)
sys.modules.setdefault("alembic.script", alembic_script_module)
sys.modules.setdefault("sqlalchemy", sqlalchemy_module)

from app.core import startup_checks
from backend import migration_service
from backend.scripts import run_release_migrations


class FakeCursor:
    def __init__(self, lock_available: bool = True) -> None:
        self.lock_available = lock_available
        self.executed: list[tuple[str, tuple[int, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[int, ...]) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> tuple[bool]:
        return (self.lock_available,)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.autocommit = False
        self.cursor_instance = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def test_check_database_revision_at_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup_checks, "alembic_config", lambda: object())
    monkeypatch.setattr(startup_checks.ScriptDirectory, "from_config", lambda _cfg: SimpleNamespace(get_heads=lambda: ["head_rev"]))
    monkeypatch.setattr(startup_checks.MigrationContext, "configure", lambda _conn: SimpleNamespace(get_current_heads=lambda: ["head_rev"]))
    monkeypatch.setattr(startup_checks, "engine", None, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "app.db.session", SimpleNamespace(engine=SimpleNamespace(connect=lambda: _Conn())))

    assert startup_checks.check_database_revision() == {
        "current_revision": "head_rev",
        "expected_revision": "head_rev",
        "at_head": True,
    }


class _Conn:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


def test_check_database_revision_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup_checks, "alembic_config", lambda: object())
    monkeypatch.setattr(startup_checks.ScriptDirectory, "from_config", lambda _cfg: SimpleNamespace(get_heads=lambda: ["expected_rev"]))
    monkeypatch.setattr(startup_checks.MigrationContext, "configure", lambda _conn: SimpleNamespace(get_current_heads=lambda: ["current_rev"]))
    monkeypatch.setitem(__import__("sys").modules, "app.db.session", SimpleNamespace(engine=SimpleNamespace(connect=lambda: _Conn())))

    assert startup_checks.check_database_revision() == {
        "current_revision": "current_rev",
        "expected_revision": "expected_rev",
        "at_head": False,
    }


def test_release_migrations_acquires_advisory_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = FakeCursor(lock_available=True)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(run_release_migrations.psycopg2, "connect", lambda _url: FakeConnection(cursor))
    run_mock = Mock()
    monkeypatch.setattr(run_release_migrations.subprocess, "run", run_mock)

    assert run_release_migrations.main() == 0

    assert cursor.executed[0][0] == "SELECT pg_try_advisory_lock(%s)"
    assert cursor.executed[-1][0] == "SELECT pg_advisory_unlock(%s)"
    run_mock.assert_called_once_with(["alembic", "upgrade", "head"], check=True)


def test_release_migrations_fails_when_advisory_lock_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = FakeCursor(lock_available=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(run_release_migrations.psycopg2, "connect", lambda _url: FakeConnection(cursor))
    run_mock = Mock()
    monkeypatch.setattr(run_release_migrations.subprocess, "run", run_mock)

    with pytest.raises(RuntimeError, match="advisory lock"):
        run_release_migrations.main()

    run_mock.assert_not_called()


def test_migration_service_success(monkeypatch: pytest.MonkeyPatch) -> None:
    run_mock = Mock()
    monkeypatch.setattr(migration_service.subprocess, "run", run_mock)

    assert migration_service.main() == 0

    run_mock.assert_called_once_with(["bash", "release.sh"], cwd=Path(migration_service.__file__).resolve().parent, check=True)


def test_migration_service_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        migration_service.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, ["bash", "release.sh"])),
    )

    assert migration_service.main() == 1


def test_release_migrations_surfaces_migration_failure_and_unlocks(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = FakeCursor(lock_available=True)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(run_release_migrations.psycopg2, "connect", lambda _url: FakeConnection(cursor))
    monkeypatch.setattr(
        run_release_migrations.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(1, ["alembic", "upgrade", "head"])),
    )

    with pytest.raises(subprocess.CalledProcessError):
        run_release_migrations.main()

    assert cursor.executed[-1][0] == "SELECT pg_advisory_unlock(%s)"
