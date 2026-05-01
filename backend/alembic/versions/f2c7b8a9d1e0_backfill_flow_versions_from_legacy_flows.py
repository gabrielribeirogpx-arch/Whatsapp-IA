"""idempotent flow/version compatibility migration with batched backfill

Revision ID: f2c7b8a9d1e0
Revises: 9f1c2d3e4a5b
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "f2c7b8a9d1e0"
down_revision = "9f1c2d3e4a5b"
branch_labels = None
depends_on = None


BATCH_SIZE = 500


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 1) Garantir colunas do modelo alvo (idempotente / sem sobrescrever dados existentes)
    op.execute("ALTER TABLE flows ADD COLUMN IF NOT EXISTS status VARCHAR")
    op.execute("ALTER TABLE flows ADD COLUMN IF NOT EXISTS current_version_id UUID")
    op.execute("ALTER TABLE flows ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE")

    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS tenant_id UUID")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS version INTEGER")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS snapshot JSONB")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS nodes JSONB")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS edges JSONB")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT false")

    # Default apenas onde status ainda está nulo.
    op.execute("UPDATE flows SET status = COALESCE(status, 'draft') WHERE status IS NULL")

    # 2/3/4/5) Backfill batelado e idempotente:
    # - Cria versão 1 apenas para flows que ainda não têm versões.
    # - Usa flows.nodes/edges quando disponíveis.
    # - Se ausente/inválido, cria payload seguro com start node.
    # - Atualiza current_version_id somente quando está nulo.
    op.execute(
        f"""
        DO $$
        DECLARE
            rows_inserted INTEGER := 0;
        BEGIN
            LOOP
                WITH candidate_flows AS (
                    SELECT
                        f.id,
                        f.tenant_id,
                        CASE
                            WHEN jsonb_typeof(to_jsonb(f.nodes)) = 'array' THEN to_jsonb(f.nodes)
                            ELSE jsonb_build_array(
                                jsonb_build_object(
                                    'id', concat('start-', f.id::text),
                                    'type', 'start',
                                    'position', jsonb_build_object('x', 0, 'y', 0),
                                    'data', jsonb_build_object('label', 'Início', 'isStart', true)
                                )
                            )
                        END AS normalized_nodes,
                        CASE
                            WHEN jsonb_typeof(to_jsonb(f.edges)) = 'array' THEN to_jsonb(f.edges)
                            ELSE '[]'::jsonb
                        END AS normalized_edges
                    FROM flows f
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM flow_versions fv
                        WHERE fv.flow_id = f.id
                    )
                    ORDER BY f.id
                    LIMIT {BATCH_SIZE}
                    FOR UPDATE OF f SKIP LOCKED
                ),
                inserted AS (
                    INSERT INTO flow_versions (
                        id,
                        flow_id,
                        tenant_id,
                        version,
                        snapshot,
                        nodes,
                        edges,
                        is_active,
                        is_published,
                        created_at
                    )
                    SELECT
                        gen_random_uuid(),
                        c.id,
                        c.tenant_id,
                        1,
                        jsonb_build_object('nodes', c.normalized_nodes, 'edges', c.normalized_edges),
                        c.normalized_nodes,
                        c.normalized_edges,
                        true,
                        false,
                        NOW()
                    FROM candidate_flows c
                    ON CONFLICT (flow_id, version) DO NOTHING
                    RETURNING flow_id, id
                )
                UPDATE flows f
                SET current_version_id = i.id
                FROM inserted i
                WHERE f.id = i.flow_id
                  AND f.current_version_id IS NULL;

                GET DIAGNOSTICS rows_inserted = ROW_COUNT;
                EXIT WHEN rows_inserted = 0;
            END LOOP;

            -- Flows que já tinham versão, mas current_version_id nulo: apontar para a versão mais nova.
            WITH latest AS (
                SELECT DISTINCT ON (fv.flow_id)
                    fv.flow_id,
                    fv.id AS version_id
                FROM flow_versions fv
                ORDER BY fv.flow_id, fv.version DESC NULLS LAST, fv.created_at DESC NULLS LAST, fv.id DESC
            )
            UPDATE flows f
            SET current_version_id = l.version_id
            FROM latest l
            WHERE f.id = l.flow_id
              AND f.current_version_id IS NULL;
        END
        $$;
        """
    )

    # Constraints e índices idempotentes para o alvo
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_versions_flow_id_version_idx ON flow_versions (flow_id, version)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flows_current_version_id ON flows (current_version_id)")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_flow_versions_flow_id_version'
            ) THEN
                ALTER TABLE flow_versions
                ADD CONSTRAINT uq_flow_versions_flow_id_version
                UNIQUE USING INDEX uq_flow_versions_flow_id_version_idx;
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    # Migração de dados/backfill não é revertida para evitar perda.
    pass
