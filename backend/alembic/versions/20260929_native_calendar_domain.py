"""add tenant-scoped native calendar persistence

Revision ID: 20260929_native_calendar
Revises: 20260928_template_cert
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260929_native_calendar"
down_revision = "20260928_template_cert"
branch_labels = None
depends_on = None


def _identity_columns():
    return (
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
    )


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def upgrade():
    # Required for GiST equality operators on UUID. It is intentionally retained
    # on downgrade because extensions can be shared by unrelated database objects.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_unique_constraint("uq_contacts_tenant_id_id", "contacts", ["tenant_id", "id"])

    op.create_table(
        "native_calendars",
        *_identity_columns(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_native_calendars_name_not_blank"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_native_calendars_tenant_id_id"),
    )
    op.create_index("ix_native_calendars_tenant_active", "native_calendars", ["tenant_id", "active"])

    op.create_table(
        "calendar_resources",
        *_identity_columns(),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_calendar_resources_name_not_blank"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            name="fk_calendar_resources_tenant_calendar", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "calendar_id", "id", name="uq_calendar_resources_tenant_calendar_id"),
    )
    op.create_index(
        "ix_calendar_resources_tenant_calendar_active", "calendar_resources", ["tenant_id", "calendar_id", "active"]
    )

    op.create_table(
        "availability_rules",
        *_identity_columns(),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_availability_rules_weekday"),
        sa.CheckConstraint("start_time < end_time", name="ck_availability_rules_time_order"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            name="fk_availability_rules_tenant_calendar", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id", "resource_id"],
            ["calendar_resources.tenant_id", "calendar_resources.calendar_id", "calendar_resources.id"],
            name="fk_availability_rules_tenant_calendar_resource", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_availability_rules_resource_weekday", "availability_rules",
        ["tenant_id", "resource_id", "weekday", "active"],
    )

    op.create_table(
        "calendar_blocks",
        *_identity_columns(),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("start_at < end_at", name="ck_calendar_blocks_time_order"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            name="fk_calendar_blocks_tenant_calendar", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id", "resource_id"],
            ["calendar_resources.tenant_id", "calendar_resources.calendar_id", "calendar_resources.id"],
            name="fk_calendar_blocks_tenant_calendar_resource", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_blocks_resource_start", "calendar_blocks", ["tenant_id", "resource_id", "start_at"])

    op.create_table(
        "appointments",
        *_identity_columns(),
        sa.Column("calendar_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_reference", sa.String(120), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="scheduled", nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("start_at < end_at", name="ck_appointments_time_order"),
        sa.CheckConstraint("status IN ('scheduled', 'cancelled', 'completed')", name="ck_appointments_status"),
        sa.CheckConstraint("source IN ('assistant', 'manual', 'api')", name="ck_appointments_source"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            name="fk_appointments_tenant_calendar", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "calendar_id", "resource_id"],
            ["calendar_resources.tenant_id", "calendar_resources.calendar_id", "calendar_resources.id"],
            name="fk_appointments_tenant_calendar_resource", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"], ["contacts.tenant_id", "contacts.id"],
            name="fk_appointments_tenant_contact", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appointments_resource_start", "appointments", ["tenant_id", "resource_id", "start_at"])
    op.create_index("ix_appointments_contact_start", "appointments", ["tenant_id", "contact_id", "start_at"])
    op.execute(
        """
        ALTER TABLE appointments ADD CONSTRAINT ex_appointments_resource_time
        EXCLUDE USING gist (
            tenant_id WITH =,
            resource_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        ) WHERE (status <> 'cancelled')
        """
    )


def downgrade():
    op.drop_table("appointments")
    op.drop_table("calendar_blocks")
    op.drop_table("availability_rules")
    op.drop_table("calendar_resources")
    op.drop_table("native_calendars")
    op.drop_constraint("uq_contacts_tenant_id_id", "contacts", type_="unique")
