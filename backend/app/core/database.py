import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from app.core.tenant import get_current_tenant_id
from app.db.base import Base
from app.models.mixins import TenantMixin

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL não configurada")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
