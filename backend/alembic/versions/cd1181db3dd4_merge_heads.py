"""merge heads

Revision ID: cd1181db3dd4
Revises: 20260424_0031, 84e7eea6fec1
Create Date: 2026-04-24 14:50:55.444057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd1181db3dd4'
down_revision: Union[str, Sequence[str], None] = ('20260424_0031', '84e7eea6fec1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
