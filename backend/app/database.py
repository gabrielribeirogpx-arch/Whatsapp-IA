"""Compatibilidade retroativa: mantenha imports antigos funcionando."""

from app.db.base import Base
from app.db.session import SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db"]
