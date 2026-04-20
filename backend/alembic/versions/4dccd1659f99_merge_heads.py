"""merge heads

Revision ID: 4dccd1659f99
Revises: 20260418_0025, 3c273990df69
Create Date: 2026-04-18 20:43:33.474589

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4dccd1659f99'
down_revision: Union[str, Sequence[str], None] = ('20260418_0025', '3c273990df69')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
