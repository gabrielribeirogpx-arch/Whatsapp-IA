"""add unique index for processed_messages tenant/message idempotency

Revision ID: 7c3d9a1b2f44
Revises: f2c1e683b036
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7c3d9a1b2f44'
down_revision: Union[str, Sequence[str], None] = 'f2c1e683b036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_processed_messages_tenant_message
    ON processed_messages (tenant_id, message_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_processed_messages_tenant_message")
