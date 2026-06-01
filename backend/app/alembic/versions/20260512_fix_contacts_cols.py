"""fix missing contacts columns in production

Revision ID: 20260512_fix_contacts_cols
Revises: 20260512_contacts_campaign_base
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260512_fix_contacts_cols"
down_revision = "20260512_contacts_campaign_base"
branch_labels = None
depends_on = None


def _columns_map(bind: sa.Connection) -> dict[str, dict]:
    inspector = sa.inspect(bind)
    return {col["name"]: col for col in inspector.get_columns("contacts")}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns_map(bind)

    if "first_name" not in cols:
        op.add_column("contacts", sa.Column("first_name", sa.String(), nullable=True))
    if "last_name" not in cols:
        op.add_column("contacts", sa.Column("last_name", sa.String(), nullable=True))
    if "email" not in cols:
        op.add_column("contacts", sa.Column("email", sa.String(), nullable=True))

    if "tags" not in cols:
        op.add_column(
            "contacts",
            sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'[]'::jsonb")),
        )
    else:
        tags_type = str(cols["tags"]["type"]).lower()
        if "json" not in tags_type:
            op.execute(
                """
                ALTER TABLE contacts
                ALTER COLUMN tags TYPE jsonb
                USING CASE
                    WHEN tags IS NULL OR btrim(tags::text) = '' THEN '[]'::jsonb
                    WHEN left(btrim(tags::text), 1) IN ('[', '{') THEN tags::jsonb
                    ELSE jsonb_build_array(tags::text)
                END
                """
            )

    if "source" not in cols:
        op.add_column("contacts", sa.Column("source", sa.String(), nullable=True, server_default=sa.text("'whatsapp'")))
    if "opt_in_status" not in cols:
        op.add_column("contacts", sa.Column("opt_in_status", sa.String(), nullable=True, server_default=sa.text("'unknown'")))
    if "last_interaction_at" not in cols:
        op.add_column("contacts", sa.Column("last_interaction_at", sa.DateTime(), nullable=True))
    if "custom_fields_json" not in cols:
        op.add_column(
            "contacts",
            sa.Column("custom_fields_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")),
        )
    if "updated_at" not in cols:
        op.add_column("contacts", sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()))

    op.execute("UPDATE contacts SET tags = '[]'::jsonb WHERE tags IS NULL")
    op.execute("UPDATE contacts SET custom_fields_json = '{}'::jsonb WHERE custom_fields_json IS NULL")
    op.execute("UPDATE contacts SET source = 'whatsapp' WHERE source IS NULL")
    op.execute("UPDATE contacts SET opt_in_status = 'unknown' WHERE opt_in_status IS NULL")
    op.execute("UPDATE contacts SET updated_at = now() WHERE updated_at IS NULL")
    op.execute(
        """
        UPDATE contacts
        SET last_interaction_at = COALESCE(last_interaction_at, last_message_at, created_at)
        WHERE last_interaction_at IS NULL
        """
    )


def downgrade() -> None:
    # Emergency safety migration: no destructive downgrade.
    pass
