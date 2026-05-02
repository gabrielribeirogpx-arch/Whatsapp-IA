"""add is_deleted column to flows

Revision ID: a6b7c8d9e0f1
Revises: f2c7b8a9d1e0
Create Date: 2026-05-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "f2c7b8a9d1e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "flows",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("UPDATE flows SET is_deleted = false WHERE is_deleted IS NULL")
    op.alter_column("flows", "is_deleted", server_default=sa.text("false"))
    op.create_index(op.f("ix_flows_is_deleted"), "flows", ["is_deleted"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_flows_is_deleted"), table_name="flows")
    op.drop_column("flows", "is_deleted")
