from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if "flow_versions" not in inspector.get_table_names():
        op.create_table(
            "flow_versions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("nodes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("edges", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["flow_id"], ["flows.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_flow_versions_flow_id"), "flow_versions", ["flow_id"], unique=False)

    inspector = inspect(bind)
    flow_columns = {column["name"] for column in inspector.get_columns("flows")}

    if "current_version_id" not in flow_columns:
        op.add_column("flows", sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index(op.f("ix_flows_current_version_id"), "flows", ["current_version_id"], unique=False)
        op.create_foreign_key(
            "fk_flows_current_version_id",
            "flows",
            "flow_versions",
            ["current_version_id"],
            ["id"],
        )

    if "published_version_id" not in flow_columns:
        op.add_column("flows", sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_index(op.f("ix_flows_published_version_id"), "flows", ["published_version_id"], unique=False)
        op.create_foreign_key(
            "fk_flows_published_version_id",
            "flows",
            "flow_versions",
            ["published_version_id"],
            ["id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    flow_columns = {column["name"] for column in inspector.get_columns("flows")}

    if "published_version_id" in flow_columns:
        op.drop_constraint("fk_flows_published_version_id", "flows", type_="foreignkey")
        op.drop_index(op.f("ix_flows_published_version_id"), table_name="flows")
        op.drop_column("flows", "published_version_id")

    if "current_version_id" in flow_columns:
        op.drop_constraint("fk_flows_current_version_id", "flows", type_="foreignkey")
        op.drop_index(op.f("ix_flows_current_version_id"), table_name="flows")
        op.drop_column("flows", "current_version_id")

    if "flow_versions" in inspect(bind).get_table_names():
        op.drop_index(op.f("ix_flow_versions_flow_id"), table_name="flow_versions")
        op.drop_table("flow_versions")
