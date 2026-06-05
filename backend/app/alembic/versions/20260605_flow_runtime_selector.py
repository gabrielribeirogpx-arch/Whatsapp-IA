"""flow runtime selector

Revision ID: 20260605_flow_runtime_selector
Revises: 20260603_flow_integrity
Create Date: 2026-06-05
"""

from alembic import op

revision = "20260605_flow_runtime_selector"
down_revision = "20260603_flow_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE flows ADD COLUMN IF NOT EXISTS runtime VARCHAR(16)")
    op.execute("UPDATE flows SET runtime = 'v1' WHERE runtime IS NULL")
    op.execute("ALTER TABLE flows ALTER COLUMN runtime SET DEFAULT 'v2'")
    op.execute("ALTER TABLE flows ALTER COLUMN runtime SET NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flows_runtime ON flows (runtime)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_flows_runtime_v1_v2'
            ) THEN
                ALTER TABLE flows
                ADD CONSTRAINT ck_flows_runtime_v1_v2 CHECK (runtime IN ('v1', 'v2'));
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flow_v2_sessions (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            flow_version_id UUID NOT NULL REFERENCES flow_versions(id) ON DELETE RESTRICT,
            contact_id UUID NULL REFERENCES contacts(id),
            conversation_id UUID NULL REFERENCES conversations(id),
            external_user_id VARCHAR(160) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            current_node_id VARCHAR(128) NULL,
            last_event_index INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_tenant_id ON flow_v2_sessions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_flow_version_id ON flow_v2_sessions (flow_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_contact_id ON flow_v2_sessions (contact_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_conversation_id ON flow_v2_sessions (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_external_user_id ON flow_v2_sessions (external_user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_status ON flow_v2_sessions (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_sessions_started_at ON flow_v2_sessions (started_at)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_v2_active_session_identity
        ON flow_v2_sessions (tenant_id, flow_version_id, external_user_id)
        WHERE status IN ('running', 'waiting')
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flow_v2_events (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            session_id UUID NOT NULL REFERENCES flow_v2_sessions(id) ON DELETE CASCADE,
            flow_version_id UUID NOT NULL REFERENCES flow_versions(id) ON DELETE RESTRICT,
            event_index INTEGER NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            event_version INTEGER NOT NULL DEFAULT 1,
            node_id VARCHAR(128) NULL,
            input_message_id VARCHAR(180) NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_flow_v2_events_session_index UNIQUE (session_id, event_index),
            CONSTRAINT uq_flow_v2_events_input_idempotency UNIQUE (tenant_id, input_message_id, event_type)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_tenant_id ON flow_v2_events (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_session_id ON flow_v2_events (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_flow_version_id ON flow_v2_events (flow_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_event_type ON flow_v2_events (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_node_id ON flow_v2_events (node_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_input_message_id ON flow_v2_events (input_message_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_events_created_at ON flow_v2_events (created_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flow_v2_scheduled_jobs (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            session_id UUID NOT NULL REFERENCES flow_v2_sessions(id) ON DELETE CASCADE,
            resume_node_id VARCHAR(128) NOT NULL,
            run_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_scheduled_jobs_tenant_id ON flow_v2_scheduled_jobs (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_scheduled_jobs_session_id ON flow_v2_scheduled_jobs (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_scheduled_jobs_resume_node_id ON flow_v2_scheduled_jobs (resume_node_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_scheduled_jobs_run_at ON flow_v2_scheduled_jobs (run_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flow_v2_idempotency_keys (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            event_kind VARCHAR(32) NOT NULL,
            idempotency_key VARCHAR(180) NOT NULL,
            session_id UUID NULL REFERENCES flow_v2_sessions(id) ON DELETE SET NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            processed_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_flow_v2_idempotency_key UNIQUE (tenant_id, event_kind, idempotency_key)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_idempotency_tenant_kind ON flow_v2_idempotency_keys (tenant_id, event_kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_idempotency_keys_tenant_id ON flow_v2_idempotency_keys (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_idempotency_keys_event_kind ON flow_v2_idempotency_keys (event_kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_idempotency_keys_idempotency_key ON flow_v2_idempotency_keys (idempotency_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_idempotency_keys_session_id ON flow_v2_idempotency_keys (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_idempotency_keys_processed_at ON flow_v2_idempotency_keys (processed_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS flow_v2_dead_letters (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            session_id UUID NULL REFERENCES flow_v2_sessions(id) ON DELETE SET NULL,
            flow_version_id UUID NULL REFERENCES flow_versions(id) ON DELETE SET NULL,
            event JSONB NOT NULL DEFAULT '{}',
            error TEXT NOT NULL,
            stacktrace TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_dead_letters_tenant_id ON flow_v2_dead_letters (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_dead_letters_session_id ON flow_v2_dead_letters (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_dead_letters_flow_version_id ON flow_v2_dead_letters (flow_version_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_v2_dead_letters_created_at ON flow_v2_dead_letters (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flow_v2_dead_letters")
    op.execute("DROP TABLE IF EXISTS flow_v2_idempotency_keys")
    op.execute("DROP TABLE IF EXISTS flow_v2_scheduled_jobs")
    op.execute("DROP TABLE IF EXISTS flow_v2_events")
    op.execute("DROP TABLE IF EXISTS flow_v2_sessions")
    op.execute("ALTER TABLE flows DROP CONSTRAINT IF EXISTS ck_flows_runtime_v1_v2")
    op.execute("DROP INDEX IF EXISTS ix_flows_runtime")
    op.execute("ALTER TABLE flows DROP COLUMN IF EXISTS runtime")
