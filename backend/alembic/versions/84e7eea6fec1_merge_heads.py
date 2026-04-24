"""merge heads

Revision ID: 84e7eea6fec1
Revises: 20260424_0029, 7c7f42c1ab55
Create Date: 2026-04-24 00:36:56.725347

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84e7eea6fec1'
down_revision: Union[str, Sequence[str], None] = ('20260424_0029', '7c7f42c1ab55')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
