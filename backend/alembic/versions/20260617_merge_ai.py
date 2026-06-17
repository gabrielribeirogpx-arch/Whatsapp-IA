"""merge ai memory heads

Revision ID: 20260617_merge_ai
Revises: 20260617_ai_ltm, 20260617_flow_ai_executions
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20260617_merge_ai"
down_revision: Union[str, Sequence[str], None] = (
    "20260617_ai_ltm",
    "20260617_flow_ai_executions",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
