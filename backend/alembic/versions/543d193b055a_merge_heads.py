"""merge heads

Revision ID: 543d193b055a
Revises: 4b9289cdf707, c9d4f1c2a001
Create Date: 2026-04-30 19:34:27.618171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '543d193b055a'
down_revision: Union[str, Sequence[str], None] = ('4b9289cdf707', 'c9d4f1c2a001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
