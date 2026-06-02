from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import NEVER_SET, NO_VALUE

from app.db.base import Base


logger = logging.getLogger(__name__)


def _worker_id() -> str:
    return str(os.getenv("WORKER_ID") or os.getenv("HOSTNAME") or os.getpid())


def set_current_node_write_reason(session: "FlowSession | None", reason: str | None) -> None:
    if session is not None:
        setattr(session, "_current_node_write_reason", str(reason or "unspecified_direct_assignment"))


def set_current_node_id(session: "FlowSession", next_node_id, reason: str | None) -> None:
    set_current_node_write_reason(session, reason)
    session.current_node_id = str(next_node_id) if next_node_id else None


FINAL_SESSION_STATUSES = {"completed", "converted", "abandoned", "expired"}


class FlowSession(Base):
    __tablename__ = "flow_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    flow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flow_versions.id"), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_identifier: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    current_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running", server_default="running")
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    variables: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



@event.listens_for(FlowSession.current_node_id, "set", retval=False)
def _log_current_node_id_write(target: FlowSession, value, oldvalue, initiator) -> None:
    old_node_id = None if oldvalue in {NEVER_SET, NO_VALUE} else oldvalue
    new_node_id = str(value) if value else None
    if old_node_id is not None and str(old_node_id) == str(new_node_id):
        return
    default_reason = "flow_session_create_initial_current_node" if oldvalue in {NEVER_SET, NO_VALUE} else "unspecified_direct_assignment"
    reason = str(getattr(target, "_current_node_write_reason", default_reason) or default_reason)
    logger.info(
        "[SESSION NODE WRITE] session_id=%s old_node_id=%s new_node_id=%s reason=%s flow_id=%s worker_id=%s",
        getattr(target, "id", None),
        old_node_id,
        new_node_id,
        reason,
        getattr(target, "flow_id", None),
        _worker_id(),
    )
