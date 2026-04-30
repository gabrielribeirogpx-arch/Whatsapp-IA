"""add flow engine tables

Revision ID: 20260418_0024
Revises: 20260418_0023
Create Date: 2026-04-18 14:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "20260418_0024"
down_revision = "20260418_0023"
branch_labels = None
depends_on = None


DEFAULT_FLOW_NAME = "__default__"
DEFAULT_FLOW_STEPS = [
    {
        "step_key": "inicio",
        "message": "Pra te ajudar melhor: vendas, suporte ou atendimento?",
        "expected_inputs": ["vendas", "suporte", "atendimento"],
        "next_step_map": '{"vendas":"tipo_atendimento","suporte":"suporte_step","atendimento":"atendimento_step"}',
    },
    {
        "step_key": "tipo_atendimento",
        "message": "Você prefere manual ou automático?",
        "expected_inputs": ["manual", "automatico"],
        "next_step_map": '{"manual":"oferta_manual","automatico":"oferta_auto"}',
    },
    {
        "step_key": "oferta_manual",
        "message": "Perfeito. Começar manual é ótimo. Quer ver os planos?",
        "expected_inputs": ["sim", "quero"],
        "next_step_map": '{"sim":"planos","quero":"planos"}',
    },
    {
        "step_key": "oferta_auto",
        "message": "Excelente. O automático acelera seu atendimento. Quer ver os planos?",
        "expected_inputs": ["sim", "quero"],
        "next_step_map": '{"sim":"planos","quero":"planos"}',
    },
    {
        "step_key": "planos",
        "message": "Temos Básico, Essencial e PRO. Qual você quer?",
        "expected_inputs": ["basico", "essencial", "pro"],
        "next_step_map": '{"basico":"fechamento","essencial":"fechamento","pro":"fechamento"}',
    },
    {
        "step_key": "fechamento",
        "message": "Posso ativar agora pra você 🚀 Quer começar?",
        "expected_inputs": ["sim", "quero"],
        "next_step_map": "null",
    },
    {
        "step_key": "suporte_step",
        "message": "Perfeito! Me conta em uma frase o que você precisa de suporte.",
        "expected_inputs": None,
        "next_step_map": "null",
    },
    {
        "step_key": "atendimento_step",
        "message": "Claro! Me diz como prefere que o atendimento aconteça hoje.",
        "expected_inputs": None,
        "next_step_map": "null",
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "flows" not in tables:
        op.create_table(
            "flows",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flows_tenant_id", "flows", ["tenant_id"], unique=False)

    if "flow_steps" not in tables:
        op.create_table(
            "flow_steps",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("step_key", sa.Text(), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("expected_inputs", postgresql.ARRAY(sa.Text()), nullable=True),
            sa.Column("next_step_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flow_steps_flow_id", "flow_steps", ["flow_id"], unique=False)
        op.create_index("ux_flow_steps_flow_id_step_key", "flow_steps", ["flow_id", "step_key"], unique=True)

    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    if "current_flow" not in conversation_columns:
        op.add_column("conversations", sa.Column("current_flow", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            "fk_conversations_current_flow_flows",
            "conversations",
            "flows",
            ["current_flow"],
            ["id"],
            ondelete="SET NULL",
        )
    if "current_step" not in conversation_columns:
        op.add_column("conversations", sa.Column("current_step", sa.Text(), nullable=True))

    # default flow seed for existing tenants
    op.execute(
        text(
            """
            INSERT INTO flows (id, tenant_id, name, created_at)
            SELECT gen_random_uuid(), t.id, :flow_name, NOW()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1
                FROM flows f
                WHERE f.tenant_id = t.id AND f.name = :flow_name
            )
            """
        ),
        {"flow_name": DEFAULT_FLOW_NAME},
    )
    for step_data in DEFAULT_FLOW_STEPS:
        op.execute(
            text(
                """
                INSERT INTO flow_steps (id, flow_id, step_key, message, expected_inputs, next_step_map, created_at)
                SELECT gen_random_uuid(), f.id, :step_key, :message, :expected_inputs, :next_step_map::jsonb, NOW()
                FROM flows f
                WHERE f.name = :flow_name
                  AND NOT EXISTS (
                    SELECT 1
                    FROM flow_steps fs
                    WHERE fs.flow_id = f.id AND fs.step_key = :step_key
                )
                """
            ),
            {
                "flow_name": DEFAULT_FLOW_NAME,
                "step_key": step_data["step_key"],
                "message": step_data["message"],
                "expected_inputs": step_data["expected_inputs"],
                "next_step_map": step_data["next_step_map"],
            },
        )


def downgrade() -> None:
    op.drop_constraint("fk_conversations_current_flow_flows", "conversations", type_="foreignkey")
    op.drop_column("conversations", "current_flow")
    op.drop_index("ux_flow_steps_flow_id_step_key", table_name="flow_steps")
    op.drop_index("ix_flow_steps_flow_id", table_name="flow_steps")
    op.drop_table("flow_steps")
    op.drop_index("ix_flows_tenant_id", table_name="flows")
    op.drop_table("flows")
