"""add automatic WhatsApp lead links

Revision ID: 20260529_lead_links
Revises: 20260529_enterprise_security
Create Date: 2026-05-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260529_lead_links"
down_revision = "20260529_enterprise_security"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {item["name"] for item in inspector.get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index_name in {item["name"] for item in inspector.get_indexes(table_name)}


def _has_fk(table_name: str, fk_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return fk_name in {item["name"] for item in inspector.get_foreign_keys(table_name)}


def _ensure_lead_link(
    column_name: str, fk_name: str, index_name: str, referent_table: str
) -> None:
    if not _has_column("leads", column_name):
        op.add_column(
            "leads",
            sa.Column(column_name, postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _has_fk("leads", fk_name):
        op.create_foreign_key(
            fk_name, "leads", referent_table, [column_name], ["id"], ondelete="SET NULL"
        )
    if not _has_index("leads", index_name):
        op.create_index(index_name, "leads", [column_name])


def upgrade() -> None:
    if not _has_column("leads", "source"):
        op.add_column(
            "leads",
            sa.Column(
                "source",
                sa.String(length=40),
                server_default="whatsapp",
                nullable=False,
            ),
        )
    _ensure_lead_link(
        "owner_id",
        "fk_leads_owner_id_tenant_users",
        "ix_leads_owner_id",
        "tenant_users",
    )
    _ensure_lead_link(
        "contact_id", "fk_leads_contact_id_contacts", "ix_leads_contact_id", "contacts"
    )
    _ensure_lead_link(
        "conversation_id",
        "fk_leads_conversation_id_conversations",
        "ix_leads_conversation_id",
        "conversations",
    )
    op.execute("UPDATE leads SET source = 'whatsapp' WHERE source IS NULL")


def downgrade() -> None:
    for column_name, fk_name, index_name in [
        (
            "conversation_id",
            "fk_leads_conversation_id_conversations",
            "ix_leads_conversation_id",
        ),
        ("contact_id", "fk_leads_contact_id_contacts", "ix_leads_contact_id"),
        ("owner_id", "fk_leads_owner_id_tenant_users", "ix_leads_owner_id"),
    ]:
        if _has_column("leads", column_name):
            if _has_index("leads", index_name):
                op.drop_index(index_name, table_name="leads")
            if _has_fk("leads", fk_name):
                op.drop_constraint(fk_name, "leads", type_="foreignkey")
            op.drop_column("leads", column_name)
    if _has_column("leads", "source"):
        op.drop_column("leads", "source")
