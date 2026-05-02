"""add is_terminal to flow_nodes if missing

Revision ID: 6d169455cf60
Revises: a6b7c8d9e0f1
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6d169455cf60"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("flow_nodes", "is_terminal"):
        op.add_column(
            "flow_nodes",
            sa.Column(
                "is_terminal",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    if _has_column("flow_nodes", "is_terminal"):
        op.drop_column("flow_nodes", "is_terminal")
