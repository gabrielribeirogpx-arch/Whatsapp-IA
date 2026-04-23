"""merge heads

Revision ID: 7c7f42c1ab55
Revises: 20260423_0028, 4dccd1659f99
Create Date: 2026-04-23 10:26:28.916103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c7f42c1ab55'
down_revision: Union[str, Sequence[str], None] = ('20260423_0028', '4dccd1659f99')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
