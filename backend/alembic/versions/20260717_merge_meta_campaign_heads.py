"""merge active alembic heads

Revision ID: 20260717_merge_meta_campaign
Revises: 20260621_pending_actions, 20260622_meta_coexistence_phase2, 20260717_campaign_analytics_indexes
Create Date: 2026-07-17
"""


revision = "20260717_merge_meta_campaign"
down_revision = (
    "20260621_pending_actions",
    "20260622_meta_coexistence_phase2",
    "20260717_campaign_analytics_indexes",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
