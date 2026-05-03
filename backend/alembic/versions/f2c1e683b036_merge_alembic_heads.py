"""merge alembic heads

Revision ID: f2c1e683b036
Revises: 6d169455cf60, aa11bb22cc33
Create Date: 2026-05-03 16:45:56.402715

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c1e683b036'
down_revision: Union[str, Sequence[str], None] = ('6d169455cf60', 'aa11bb22cc33')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
