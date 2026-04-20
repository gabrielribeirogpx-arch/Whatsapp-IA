from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "contacts" not in inspector.get_table_names():
        op.create_table(
            "contacts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("phone", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("avatar_url", sa.String(), nullable=True),
            sa.Column("stage", sa.String(), nullable=False, server_default="novo"),
            sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_message_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "phone", name="uq_contacts_tenant_phone"),
        )

    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("contacts")}
    contacts_phone_index = op.f("ix_contacts_phone")
    contacts_tenant_index = op.f("ix_contacts_tenant_id")
    if contacts_phone_index not in existing_indexes:
        op.create_index(contacts_phone_index, "contacts", ["phone"], unique=False)
    if contacts_tenant_index not in existing_indexes:
        op.create_index(contacts_tenant_index, "contacts", ["tenant_id"], unique=False)

    op.add_column("conversations", sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f("ix_conversations_contact_id"), "conversations", ["contact_id"], unique=False)
    op.create_foreign_key("fk_conversations_contact_id", "conversations", "contacts", ["contact_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_conversations_contact_id", "conversations", type_="foreignkey")
    op.drop_index(op.f("ix_conversations_contact_id"), table_name="conversations")
    op.drop_column("conversations", "contact_id")

    op.drop_index(op.f("ix_contacts_tenant_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_phone"), table_name="contacts")
    op.drop_table("contacts")
