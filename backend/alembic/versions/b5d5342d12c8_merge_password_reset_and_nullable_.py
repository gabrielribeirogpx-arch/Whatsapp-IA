"""merge password reset and nullable whatsapp credentials heads

Revision ID: b5d5342d12c8
Revises: 20260527_password_reset, 9572968f1bd3
Create Date: 2026-05-27 21:14:10.929022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d5342d12c8'
down_revision: Union[str, Sequence[str], None] = ('20260527_password_reset', '9572968f1bd3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
