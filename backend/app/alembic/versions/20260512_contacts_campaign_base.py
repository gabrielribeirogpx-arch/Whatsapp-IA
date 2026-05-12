"""contacts campaign base fields

Revision ID: 20260512_contacts_campaign_base
Revises: 20260511_whatsapp_campaigns_runtime
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260512_contacts_campaign_base"
down_revision = "20260511_whatsapp_campaigns_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("first_name", sa.String(), nullable=True))
    op.add_column("contacts", sa.Column("last_name", sa.String(), nullable=True))
    op.add_column("contacts", sa.Column("email", sa.String(), nullable=True))
    op.add_column("contacts", sa.Column("tags", sa.String(), nullable=True))
    op.add_column("contacts", sa.Column("source", sa.String(), nullable=True, server_default="whatsapp"))
    op.add_column("contacts", sa.Column("opt_in_status", sa.String(), nullable=True, server_default="unknown"))
    op.add_column("contacts", sa.Column("last_interaction_at", sa.DateTime(), nullable=True))
    op.add_column("contacts", sa.Column("custom_fields_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("contacts", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column("contacts", "updated_at")
    op.drop_column("contacts", "custom_fields_json")
    op.drop_column("contacts", "last_interaction_at")
    op.drop_column("contacts", "opt_in_status")
    op.drop_column("contacts", "source")
    op.drop_column("contacts", "tags")
    op.drop_column("contacts", "email")
    op.drop_column("contacts", "last_name")
    op.drop_column("contacts", "first_name")
