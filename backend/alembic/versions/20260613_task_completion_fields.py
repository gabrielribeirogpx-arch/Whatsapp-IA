"""add task completion fields

Revision ID: 20260613_task_completion_fields
Revises: 20260613_create_tasks
Create Date: 2026-06-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260613_task_completion_fields"
down_revision: Union[str, Sequence[str], None] = "20260613_create_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("tasks"):
        return
    if not _has_column("tasks", "completed_at"):
        op.add_column("tasks", sa.Column("completed_at", sa.DateTime(), nullable=True))
    if not _has_column("tasks", "completed_by"):
        op.add_column("tasks", sa.Column("completed_by", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    if not _has_table("tasks"):
        return
    if _has_column("tasks", "completed_by"):
        op.drop_column("tasks", "completed_by")
    if _has_column("tasks", "completed_at"):
        op.drop_column("tasks", "completed_at")
