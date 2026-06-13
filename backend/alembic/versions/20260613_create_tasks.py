"""create tasks table

Revision ID: 20260613_create_tasks
Revises: 20260608_assigned_user_name
Create Date: 2026-06-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260613_create_tasks"
down_revision: Union[str, Sequence[str], None] = "20260608_assigned_user_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if not _has_table("tasks"):
        op.create_table(
            "tasks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
            sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
            sa.Column("assigned_to", sa.String(length=150), nullable=True),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in {
        "ix_tasks_tenant_id": ["tenant_id"],
        "ix_tasks_conversation_id": ["conversation_id"],
        "ix_tasks_contact_id": ["contact_id"],
        "ix_tasks_lead_id": ["lead_id"],
        "ix_tasks_tenant_status_due_at": ["tenant_id", "status", "due_at"],
        "ix_tasks_tenant_conversation": ["tenant_id", "conversation_id"],
        "ix_tasks_tenant_contact": ["tenant_id", "contact_id"],
        "ix_tasks_tenant_lead": ["tenant_id", "lead_id"],
    }.items():
        if not _has_index("tasks", name):
            op.create_index(name, "tasks", cols)


def downgrade() -> None:
    if _has_table("tasks"):
        op.drop_table("tasks")
