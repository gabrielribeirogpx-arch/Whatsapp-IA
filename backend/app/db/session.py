"""Compat layer for projects expecting app.db.session."""

from app.core.database import SessionLocal, engine, get_db

__all__ = ["SessionLocal", "engine", "get_db"]
