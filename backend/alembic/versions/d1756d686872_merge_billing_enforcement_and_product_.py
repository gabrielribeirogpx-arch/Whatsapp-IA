"""merge billing enforcement and product analytics heads

Revision ID: d1756d686872
Revises: 20260722_billing_enforcement, 20260723_product_analytics
Create Date: 2026-07-24 01:09:33.192422

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1756d686872'
down_revision: Union[str, Sequence[str], None] = ('20260722_billing_enforcement', '20260723_product_analytics')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
