"""Persistent live voice workspaces and private provider sessions."""
from alembic import op
import sqlalchemy as sa

revision = "149_live_voice_workspaces"
down_revision = "148_expert_async_tool_prompts"
branch_labels = None
depends_on = None

TABLES = ['workspace_agent_deployments', 'workspace_chats', 'workspace_artifacts', 'workspace_conversation_sessions', 'workspace_expert_threads', 'workspace_operations', 'workspace_references', 'workspace_artifact_revisions', 'workspace_conversation_events', 'workspace_research', 'workspace_sources']


def upgrade():
    op.create_table('workspace_agent_deployments',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('kunder.id', ondelete='RESTRICT'), nullable=False, primary_key=False),
        sa.Column('language', sa.String(8), nullable=False, primary_key=False),
        sa.Column('expert_id', sa.String(64), sa.ForeignKey('personas.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('prompt_version', sa.String(64), nullable=False, primary_key=False),
        sa.Column('agent_id', sa.String(128), nullable=False, primary_key=False),
        sa.Column('agent_version', sa.String(128), nullable=False, primary_key=False),
        sa.Column('tool_ids', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('procedure_ids', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('customer_id', 'language', 'expert_id', 'prompt_version', name='uq_workspace_agent_snapshot'),
    )
    op.create_index('ix_workspace_agent_deployments_customer_id', 'workspace_agent_deployments', ['customer_id'], unique=False)
    op.create_index('ix_workspace_agent_deployments_expert_id', 'workspace_agent_deployments', ['expert_id'], unique=False)
    op.create_table('workspace_chats',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('kunder.id', ondelete='RESTRICT'), nullable=False, primary_key=False),
        sa.Column('owner_user_id', sa.String(64), sa.ForeignKey('user_accounts.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('creation_key', sa.String(160), nullable=False),
        sa.Column('creation_payload_hash', sa.String(64), nullable=False),
        sa.Column('title', sa.String(255), nullable=False, primary_key=False),
        sa.Column('module', sa.String(32), nullable=False, primary_key=False),
        sa.Column('revision', sa.Integer(), nullable=False, primary_key=False, server_default=sa.text('0')),
        sa.Column('next_reference_number', sa.Integer(), nullable=False, primary_key=False, server_default=sa.text('1')),
        sa.Column('state', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('owner_user_id', 'creation_key', name='uq_workspace_creation_key'),
    )
    op.create_index('ix_workspace_chats_customer_id', 'workspace_chats', ['customer_id'], unique=False)
    op.create_index('ix_workspace_chats_owner_user_id', 'workspace_chats', ['owner_user_id'], unique=False)
    op.create_table('workspace_artifacts',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('kind', sa.String(24), nullable=False, primary_key=False),
        sa.Column('title', sa.String(255), nullable=False, primary_key=False),
        sa.Column('status', sa.String(24), nullable=False, primary_key=False),
        sa.Column('revision', sa.Integer(), nullable=False, primary_key=False, server_default=sa.text('0')),
        sa.Column('content', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True, primary_key=False),
        sa.Column('error', sa.Text(), nullable=True, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_workspace_artifacts_workspace_id', 'workspace_artifacts', ['workspace_id'], unique=False)
    op.create_table('workspace_conversation_sessions',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('user_id', sa.String(64), sa.ForeignKey('user_accounts.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('kunder.id', ondelete='RESTRICT'), nullable=False, primary_key=False),
        sa.Column('expert_id', sa.String(64), sa.ForeignKey('personas.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('mode', sa.String(8), nullable=False, primary_key=False),
        sa.Column('language', sa.String(8), nullable=False, primary_key=False),
        sa.Column('generation', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('conversation_id', sa.String(128), nullable=True, primary_key=False),
        sa.Column('status', sa.String(16), nullable=False, primary_key=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column('prompt_version', sa.String(64), nullable=False, primary_key=False),
        sa.Column('agent_version', sa.String(128), nullable=False, primary_key=False),
        sa.Column('agent_id', sa.String(128), nullable=False, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('conversation_id', name=None),
        sa.UniqueConstraint('workspace_id', 'generation', name='uq_workspace_conversation_generation'),
    )
    op.create_index('ix_workspace_conversation_sessions_customer_id', 'workspace_conversation_sessions', ['customer_id'], unique=False)
    op.create_index('ix_workspace_conversation_sessions_expert_id', 'workspace_conversation_sessions', ['expert_id'], unique=False)
    op.create_index('ix_workspace_conversation_sessions_status', 'workspace_conversation_sessions', ['status'], unique=False)
    op.create_index('ix_workspace_conversation_sessions_user_id', 'workspace_conversation_sessions', ['user_id'], unique=False)
    op.create_index('ix_workspace_conversation_sessions_workspace_id', 'workspace_conversation_sessions', ['workspace_id'], unique=False)
    op.create_table('workspace_expert_threads',
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('expert_id', sa.String(64), sa.ForeignKey('personas.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_table('workspace_operations',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('idempotency_key', sa.String(160), nullable=False, primary_key=False),
        sa.Column('payload_hash', sa.String(64), nullable=False, primary_key=False),
        sa.Column('tool_name', sa.String(64), nullable=False, primary_key=False),
        sa.Column('status', sa.String(24), nullable=False, primary_key=False),
        sa.Column('context_snapshot', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('result', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_workspace_operation_key'),
    )
    op.create_index('ix_workspace_operations_workspace_id', 'workspace_operations', ['workspace_id'], unique=False)
    op.create_table('workspace_references',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('number', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('identity_key', sa.String(64), nullable=False, primary_key=False),
        sa.Column('kind', sa.String(24), nullable=False, primary_key=False),
        sa.Column('source_id', sa.String(512), nullable=False, primary_key=False),
        sa.Column('source_version', sa.String(64), nullable=False, primary_key=False),
        sa.Column('anchor', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('snapshot', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('workspace_id', 'identity_key', name='uq_workspace_reference_identity'),
        sa.UniqueConstraint('workspace_id', 'number', name='uq_workspace_reference_number'),
    )
    op.create_index('ix_workspace_references_workspace_id', 'workspace_references', ['workspace_id'], unique=False)
    op.create_table('workspace_artifact_revisions',
        sa.Column('artifact_id', sa.String(36), sa.ForeignKey('workspace_artifacts.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('title', sa.String(255), nullable=False, primary_key=False),
        sa.Column('content', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_table('workspace_conversation_events',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('workspace_conversation_sessions.id', ondelete='CASCADE'), nullable=False, primary_key=False),
        sa.Column('event_key', sa.String(160), nullable=False, primary_key=False),
        sa.Column('kind', sa.String(16), nullable=False, primary_key=False),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('persona_messages.id', ondelete='SET NULL'), nullable=True, primary_key=False),
        sa.Column('payload', sa.JSON(), nullable=False, primary_key=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('session_id', 'event_key', name='uq_workspace_conversation_event'),
    )
    op.create_index('ix_workspace_conversation_events_session_id', 'workspace_conversation_events', ['session_id'], unique=False)
    op.create_table('workspace_research',
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('attempt_id', sa.String(64), sa.ForeignKey('execution_attempts.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_table('workspace_sources',
        sa.Column('source_url', sa.String(2048), nullable=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace_chats.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('source_id', sa.String(64), sa.ForeignKey('stored_objects.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, primary_key=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    if op.get_bind().dialect.name == "postgresql":
        for name in TABLES:
            op.execute(sa.text(f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY'))
            op.execute(sa.text(f'REVOKE ALL ON TABLE public."{name}" FROM PUBLIC'))
            for role in ("anon", "authenticated"):
                op.execute(sa.text(f'DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = \'{role}\') THEN REVOKE ALL ON TABLE public."{name}" FROM "{role}"; END IF; END $$'))


def downgrade():
    op.drop_table('workspace_sources')
    op.drop_table('workspace_research')
    op.drop_table('workspace_conversation_events')
    op.drop_table('workspace_artifact_revisions')
    op.drop_table('workspace_references')
    op.drop_table('workspace_operations')
    op.drop_table('workspace_expert_threads')
    op.drop_table('workspace_conversation_sessions')
    op.drop_table('workspace_artifacts')
    op.drop_table('workspace_chats')
    op.drop_table('workspace_agent_deployments')
