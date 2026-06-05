"""flow snapshot integrity metadata

Revision ID: 20260603_flow_integrity
Revises: 20260601_release_hidden_phone
Create Date: 2026-06-03
"""

from __future__ import annotations

revision = "20260603_flow_integrity"
down_revision = "20260601_release_hidden_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # flow_versions already stores the canonical graph in nodes/edges/snapshot.
    # No extra JSON/count/hash columns are required for compatibility.
    pass


def downgrade() -> None:
    # No-op: upgrade does not add flow_versions compatibility columns.
    pass
