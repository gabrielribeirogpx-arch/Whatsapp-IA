"""Compat layer for projects expecting app.db.base."""

from app.core.database import Base

__all__ = ["Base"]
