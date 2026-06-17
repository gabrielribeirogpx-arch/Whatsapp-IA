"""add flow ai long term memory

Revision ID: 20260617_ai_ltm
Revises: 20260508_pub_sess_hard
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = '20260617_ai_ltm'
down_revision = '20260508_pub_sess_hard'
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector, table: str, name: str) -> bool:
    return name in {idx['name'] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _has_table(inspector, 'flow_ai_long_term_memory'):
        op.create_table(
            'flow_ai_long_term_memory',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('contact_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
            sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True),
            sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('flow_v2_sessions.id', ondelete='SET NULL'), nullable=True),
            sa.Column('fact_text', sa.Text(), nullable=False),
            sa.Column('fact_embedding_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column('fact_type', sa.String(length=64), nullable=False, server_default='custom'),
            sa.Column('importance_score', sa.Numeric(4, 3), nullable=False, server_default='0.5'),
            sa.Column('source', sa.String(length=120), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        )
        inspector = inspect(bind)
    for name, cols in {
        'ix_flow_ai_ltm_tenant_id': ['tenant_id'], 'ix_flow_ai_ltm_contact_id': ['contact_id'],
        'ix_flow_ai_ltm_conversation_id': ['conversation_id'], 'ix_flow_ai_ltm_fact_type': ['fact_type'],
        'ix_flow_ai_ltm_created_at': ['created_at'],
    }.items():
        if not _has_index(inspector, 'flow_ai_long_term_memory', name):
            op.create_index(name, 'flow_ai_long_term_memory', cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind(); inspector = inspect(bind)
    if _has_table(inspector, 'flow_ai_long_term_memory'):
        op.drop_table('flow_ai_long_term_memory')
