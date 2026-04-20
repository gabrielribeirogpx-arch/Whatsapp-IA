"""merge heads

Revision ID: 414541adc4b5
Revises: 20260418_0022, 20260416_0016
Create Date: 2026-04-18 04:38:24.161112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '414541adc4b5'
down_revision: Union[str, Sequence[str], None] = ('20260418_0022', '20260416_0016')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
