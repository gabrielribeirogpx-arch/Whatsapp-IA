"""add source_handle to flow_edges

Revision ID: 20260420_0026
Revises: 20260418_0025
Create Date: 2026-04-20 12:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260420_0026"
down_revision = "20260418_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column["name"] for column in inspector.get_columns("flow_edges")}
    if "source_handle" not in columns:
        op.add_column("flow_edges", sa.Column("source_handle", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {column["name"] for column in inspector.get_columns("flow_edges")}
    if "source_handle" in columns:
        op.drop_column("flow_edges", "source_handle")
