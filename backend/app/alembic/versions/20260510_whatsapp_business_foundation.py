"""whatsapp business foundation

Revision ID: 20260510_whatsapp_business
Revises: 20260510_conversations_current_node_runtime_obsolete
Create Date: 2026-05-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260510_whatsapp_business'
down_revision = '20260510_conversations_current_node_runtime_obsolete'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tenant_whatsapp_providers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider_type', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=True),
        sa.Column('waba_id', sa.String(length=120), nullable=True),
        sa.Column('phone_number_id', sa.String(length=120), nullable=True),
        sa.Column('business_id', sa.String(length=120), nullable=True),
        sa.Column('bsp_account_id', sa.String(length=120), nullable=True),
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('app_id', sa.String(length=120), nullable=True),
        sa.Column('app_secret_encrypted', sa.Text(), nullable=True),
        sa.Column('api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('webhook_verify_token', sa.String(length=255), nullable=True),
        sa.Column('webhook_url', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('status', sa.String(length=40), server_default='disconnected', nullable=False),
        sa.Column('last_connection_check_at', sa.DateTime(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tenant_whatsapp_providers_tenant_id', 'tenant_whatsapp_providers', ['tenant_id'])
    op.create_index('ix_tenant_whatsapp_providers_tenant_provider', 'tenant_whatsapp_providers', ['tenant_id', 'provider_type'])
    op.create_index('ix_tenant_whatsapp_providers_tenant_active', 'tenant_whatsapp_providers', ['tenant_id', 'is_active'])
    op.create_index('uq_tenant_single_active_provider', 'tenant_whatsapp_providers', ['tenant_id'], unique=True, postgresql_where=sa.text('is_active = true'))

    op.create_table(
        'whatsapp_message_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('language', sa.String(length=20), server_default='pt_BR', nullable=False),
        sa.Column('status', sa.String(length=40), server_default='draft', nullable=False),
        sa.Column('external_template_id', sa.String(length=180), nullable=True),
        sa.Column('external_status', sa.String(length=80), nullable=True),
        sa.Column('header_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('body_text', sa.Text(), nullable=False),
        sa.Column('footer_text', sa.Text(), nullable=True),
        sa.Column('buttons_json', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('variables_json', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['provider_id'], ['tenant_whatsapp_providers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_whatsapp_message_templates_tenant_id', 'whatsapp_message_templates', ['tenant_id'])
    op.create_index('ix_whatsapp_message_templates_tenant_status', 'whatsapp_message_templates', ['tenant_id', 'status'])
    op.create_index('ix_whatsapp_message_templates_tenant_name', 'whatsapp_message_templates', ['tenant_id', 'name'])
    op.create_index('ix_whatsapp_message_templates_provider_id', 'whatsapp_message_templates', ['provider_id'])


def downgrade() -> None:
    op.drop_index('ix_whatsapp_message_templates_provider_id', table_name='whatsapp_message_templates')
    op.drop_index('ix_whatsapp_message_templates_tenant_name', table_name='whatsapp_message_templates')
    op.drop_index('ix_whatsapp_message_templates_tenant_status', table_name='whatsapp_message_templates')
    op.drop_index('ix_whatsapp_message_templates_tenant_id', table_name='whatsapp_message_templates')
    op.drop_table('whatsapp_message_templates')
    op.drop_index('uq_tenant_single_active_provider', table_name='tenant_whatsapp_providers')
    op.drop_index('ix_tenant_whatsapp_providers_tenant_active', table_name='tenant_whatsapp_providers')
    op.drop_index('ix_tenant_whatsapp_providers_tenant_provider', table_name='tenant_whatsapp_providers')
    op.drop_index('ix_tenant_whatsapp_providers_tenant_id', table_name='tenant_whatsapp_providers')
    op.drop_table('tenant_whatsapp_providers')
