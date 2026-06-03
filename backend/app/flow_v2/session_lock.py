from __future__ import annotations

import threading
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class FlowV2SessionLockError(RuntimeError):
    pass


class FlowV2SessionLock:
    """One-session/one-executor lock for Runtime V2.

    PostgreSQL deployments use transaction-scoped advisory locks. Unit tests and
    non-Postgres fakes fall back to a process-local non-blocking lock.
    """

    _locks: dict[str, threading.Lock] = {}
    _guard = threading.Lock()

    @contextmanager
    def acquire(self, db: Session, *, tenant_id: UUID, session_id: UUID):
        key = f"{tenant_id}:{session_id}"
        if hasattr(db, "execute"):
            try:
                result = db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": key})
                if not bool(result.scalar()):
                    raise FlowV2SessionLockError("Runtime V2 session is already executing")
                yield
                return
            except FlowV2SessionLockError:
                raise
            except Exception:
                pass

        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=False):
            raise FlowV2SessionLockError("Runtime V2 session is already executing")
        try:
            yield
        finally:
            lock.release()
