"""Compat layer for projects expecting app.db.session."""

from app.core.database import SessionLocal, dispose_engine_connections_after_fork, engine, get_db

__all__ = ["SessionLocal", "dispose_engine_connections_after_fork", "engine", "get_db"]
