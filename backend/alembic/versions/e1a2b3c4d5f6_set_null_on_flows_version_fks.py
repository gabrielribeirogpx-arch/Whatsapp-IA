"""set null on flow version foreign keys

Revision ID: e1a2b3c4d5f6
Revises: 543d193b055a
Create Date: 2026-04-30 20:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "543d193b055a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CURRENT_FK_NAME = "fk_flows_current_version_id_flow_versions"
PUBLISHED_FK_NAME = "fk_flows_published_version_id_flow_versions"


def _drop_fk_if_exists(column_name: str) -> None:
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                constraint_name text;
            BEGIN
                SELECT tc.constraint_name
                INTO constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = 'flows'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = :column_name
                LIMIT 1;

                IF constraint_name IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE flows DROP CONSTRAINT %I', constraint_name);
                END IF;
            END$$;
            """
        ).bindparams(column_name=column_name)
    )


def upgrade() -> None:
    _drop_fk_if_exists("current_version_id")
    _drop_fk_if_exists("published_version_id")

    op.alter_column(
        "flows",
        "current_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "flows",
        "published_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    op.create_foreign_key(
        CURRENT_FK_NAME,
        "flows",
        "flow_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        PUBLISHED_FK_NAME,
        "flows",
        "flow_versions",
        ["published_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_flows_current_version_id ON flows (current_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flows_published_version_id ON flows (published_version_id)")


def downgrade() -> None:
    op.drop_constraint(CURRENT_FK_NAME, "flows", type_="foreignkey")
    op.drop_constraint(PUBLISHED_FK_NAME, "flows", type_="foreignkey")

    op.create_foreign_key(
        CURRENT_FK_NAME,
        "flows",
        "flow_versions",
        ["current_version_id"],
        ["id"],
    )
    op.create_foreign_key(
        PUBLISHED_FK_NAME,
        "flows",
        "flow_versions",
        ["published_version_id"],
        ["id"],
    )
