"""merge heads

Revision ID: 3c273990df69
Revises: 20260418_0023, 414541adc4b5
Create Date: 2026-04-18 17:15:54.853258

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c273990df69'
down_revision: Union[str, Sequence[str], None] = ('20260418_0023', '414541adc4b5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
