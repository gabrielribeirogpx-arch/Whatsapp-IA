"""merge final heads

Revision ID: da4e2fa678e1
Revises: 20260424_0035, cd1181db3dd4
Create Date: 2026-04-24 18:53:00.469532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da4e2fa678e1'
down_revision: Union[str, Sequence[str], None] = ('20260424_0035', 'cd1181db3dd4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
