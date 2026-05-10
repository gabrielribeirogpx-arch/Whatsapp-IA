"""allow nullable whatsapp credentials on tenants

Revision ID: 9572968f1bd3
Revises: 20260508_pub_sess_hard
Create Date: 2026-05-10 01:22:51.097286

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9572968f1bd3'
down_revision: Union[str, Sequence[str], None] = '20260508_pub_sess_hard'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenants
        ALTER COLUMN phone_number_id DROP NOT NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE tenants
        ALTER COLUMN whatsapp_token DROP NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenants
        ALTER COLUMN phone_number_id SET NOT NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE tenants
        ALTER COLUMN whatsapp_token SET NOT NULL;
        """
    )
