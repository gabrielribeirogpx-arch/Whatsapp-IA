"""add automatic WhatsApp lead links

Revision ID: 20260529_auto_whatsapp_lead_links
Revises: 20260529_enterprise_security
Create Date: 2026-05-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260529_auto_whatsapp_lead_links"
down_revision = "20260529_enterprise_security"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {item["name"] for item in inspector.get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index_name in {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _has_column("leads", "source"):
        op.add_column("leads", sa.Column("source", sa.String(length=40), server_default="whatsapp", nullable=False))
    if not _has_column("leads", "owner_id"):
        op.add_column("leads", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key("fk_leads_owner_id_tenant_users", "leads", "tenant_users", ["owner_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_leads_owner_id", "leads", ["owner_id"])
    if not _has_column("leads", "contact_id"):
        op.add_column("leads", sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key("fk_leads_contact_id_contacts", "leads", "contacts", ["contact_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_leads_contact_id", "leads", ["contact_id"])
    if not _has_column("leads", "conversation_id"):
        op.add_column("leads", sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key("fk_leads_conversation_id_conversations", "leads", "conversations", ["conversation_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_leads_conversation_id", "leads", ["conversation_id"])
    op.execute("UPDATE leads SET source = 'whatsapp' WHERE source IS NULL")


def downgrade() -> None:
    for column_name, fk_name, index_name in [
        ("conversation_id", "fk_leads_conversation_id_conversations", "ix_leads_conversation_id"),
        ("contact_id", "fk_leads_contact_id_contacts", "ix_leads_contact_id"),
        ("owner_id", "fk_leads_owner_id_tenant_users", "ix_leads_owner_id"),
    ]:
        if _has_column("leads", column_name):
            if _has_index("leads", index_name):
                op.drop_index(index_name, table_name="leads")
            op.drop_constraint(fk_name, "leads", type_="foreignkey")
            op.drop_column("leads", column_name)
    if _has_column("leads", "source"):
        op.drop_column("leads", "source")
