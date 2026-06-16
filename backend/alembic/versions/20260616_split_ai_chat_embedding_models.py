"""split tenant ai chat and embedding models

Revision ID: 20260616_split_ai_models
Revises: 20260615_tenant_ai_settings
Create Date: 2026-06-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_split_ai_models"
down_revision = "20260615_tenant_ai_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("tenant_ai_settings")}
    if "model" in columns and "chat_model" not in columns:
        op.alter_column("tenant_ai_settings", "model", new_column_name="chat_model", existing_type=sa.String(length=120), nullable=True)
    elif "chat_model" not in columns:
        op.add_column("tenant_ai_settings", sa.Column("chat_model", sa.String(length=120), nullable=True))
    if "embedding_model" not in columns:
        op.add_column("tenant_ai_settings", sa.Column("embedding_model", sa.String(length=120), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("tenant_ai_settings")}
    if "chat_model" in columns and "model" not in columns:
        op.alter_column("tenant_ai_settings", "chat_model", new_column_name="model", existing_type=sa.String(length=120), nullable=True)
