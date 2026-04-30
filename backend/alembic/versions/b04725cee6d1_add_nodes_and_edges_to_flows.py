"""add nodes and edges to flows

Revision ID: b04725cee6d1
Revises: b730b9822805
Create Date: 2026-04-30 20:44:48.075304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b04725cee6d1'
down_revision: Union[str, Sequence[str], None] = 'b730b9822805'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('flows', sa.Column('nodes', sa.JSON(), nullable=True))
    op.add_column('flows', sa.Column('edges', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('flows', 'nodes')
    op.drop_column('flows', 'edges')
