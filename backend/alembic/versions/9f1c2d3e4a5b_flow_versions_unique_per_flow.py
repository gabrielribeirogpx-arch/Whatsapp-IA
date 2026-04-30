"""deduplicate flow_versions and enforce unique (flow_id, version)

Revision ID: 9f1c2d3e4a5b
Revises: e1a2b3c4d5f6
Create Date: 2026-04-30
"""

from alembic import op


revision = "9f1c2d3e4a5b"
down_revision = "e1a2b3c4d5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ordered AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY flow_id
                    ORDER BY created_at ASC NULLS FIRST, id ASC
                ) AS normalized_version
            FROM flow_versions
        )
        UPDATE flow_versions fv
        SET version = ordered.normalized_version
        FROM ordered
        WHERE fv.id = ordered.id
        """
    )

    op.create_unique_constraint(
        "uq_flow_versions_flow_id_version",
        "flow_versions",
        ["flow_id", "version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_flow_versions_flow_id_version",
        "flow_versions",
        type_="unique",
    )
