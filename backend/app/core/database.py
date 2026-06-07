import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from app.core.tenant import get_current_tenant_id
from app.db.base import Base
from app.models.mixins import TenantMixin

DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_POOL_RECYCLE_SECONDS = 300

if not DATABASE_URL:
    raise Exception("DATABASE_URL não configurada")


def _pool_recycle_seconds() -> int:
    raw_value = os.getenv("DB_POOL_RECYCLE_SECONDS", str(DEFAULT_POOL_RECYCLE_SECONDS)).strip()
    try:
        return int(raw_value)
    except ValueError:
        return DEFAULT_POOL_RECYCLE_SECONDS


def create_sqlalchemy_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=_pool_recycle_seconds(),
    )


engine = create_sqlalchemy_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def dispose_engine_connections_after_fork() -> None:
    """Drop inherited pooled DB sockets in forked worker children.

    SQLAlchemy Engine objects are thread-safe, but pooled DBAPI sockets must not be
    reused after a process fork. RQ/Railway worker processes can fork after imports,
    so each child must start with an empty pool and open fresh PostgreSQL sockets.
    """
    engine.dispose(close=False)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=dispose_engine_connections_after_fork)


@event.listens_for(Session, "do_orm_execute")
def _add_tenant_criteria(execute_state):
    if not execute_state.is_select:
        return
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
