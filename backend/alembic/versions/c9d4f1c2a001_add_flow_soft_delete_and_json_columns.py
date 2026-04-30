"""add flow soft delete and json graph columns

Revision ID: c9d4f1c2a001
Revises: b04725cee6d1
Create Date: 2026-04-30 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d4f1c2a001'
down_revision: Union[str, Sequence[str], None] = 'b04725cee6d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('flows', sa.Column('nodes_json', sa.JSON(), nullable=True))
    op.add_column('flows', sa.Column('edges_json', sa.JSON(), nullable=True))
    op.add_column('flows', sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('flows', 'deleted_at')
    op.drop_column('flows', 'edges_json')
    op.drop_column('flows', 'nodes_json')
