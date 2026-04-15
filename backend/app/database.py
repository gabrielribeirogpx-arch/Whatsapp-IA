"""Compatibilidade retroativa: mantenha imports antigos funcionando."""

from app.core.database import Base, SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db"]
