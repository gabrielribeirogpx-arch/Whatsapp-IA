"""Compat layer for projects expecting app.db.base."""

from backend.app.core.database import Base

__all__ = ["Base"]
