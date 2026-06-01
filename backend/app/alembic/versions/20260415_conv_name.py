"""add conversation names

Revision ID: 20260415_conv_name
Revises: 20260415_contacts_conv
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_conv_name"
down_revision = "20260415_contacts_conv"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversations', sa.Column('name', sa.String(), nullable=True))


def downgrade():
    op.drop_column('conversations', 'name')
