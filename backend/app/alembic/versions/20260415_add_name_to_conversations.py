from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('conversations', sa.Column('name', sa.String(), nullable=True))

def downgrade():
    op.drop_column('conversations', 'name')
