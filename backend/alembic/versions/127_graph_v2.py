"""Graph v2 property graph. Existing claim tables remain for research read-through during cutover.

Revision ID: 127_graph_v2
Revises: 126_knowledge_claim_source_independence
"""

import sqlalchemy as sa
from alembic import op

revision = "127_graph_v2"
down_revision = "126_knowledge_claim_source_independence"
branch_labels = None
depends_on = None


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("kunder.id"), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        *_scope_columns(),
        sa.Column("node_type", sa.String(128), nullable=False),
        sa.Column("identity_key", sa.String(512), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("scope_key", "node_type", "identity_key", name="uq_graph_node_identity"),
        sa.CheckConstraint("(scope_key = 'shared' AND customer_id IS NULL) OR "
                           "(scope_key = 'customer:' || customer_id AND customer_id IS NOT NULL)",
                           name="ck_graph_node_scope"),
    )
    op.create_index("ix_graph_node_name", "graph_nodes", ["scope_key", "node_type", "normalized_name"])
    op.create_index("ix_graph_nodes_scope_key", "graph_nodes", ["scope_key"])
    op.create_table(
        "graph_identifiers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("namespace", sa.String(128), nullable=False),
        sa.Column("identifier", sa.String(512), nullable=False),
        sa.Column("node_id", sa.String(64), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("scope_key", "namespace", "identifier", name="uq_graph_identifier"),
    )
    op.create_index("ix_graph_identifier_node", "graph_identifiers", ["node_id"])
    op.create_table(
        "graph_facts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("identity_key", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("target_id", sa.String(64), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("context_id", sa.String(64), sa.ForeignKey("graph_nodes.id"), nullable=True),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column("fact_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("occurrence_key", sa.String(256), nullable=False),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.UniqueConstraint("scope_key", "identity_key", name="uq_graph_fact_identity"),
        sa.CheckConstraint("(scope_key = 'shared' AND customer_id IS NULL) OR "
                           "(scope_key = 'customer:' || customer_id AND customer_id IS NOT NULL)",
                           name="ck_graph_fact_scope"),
    )
    op.create_index("ix_graph_facts_scope_key", "graph_facts", ["scope_key"])
    op.create_index("ix_graph_fact_endpoints", "graph_facts", ["scope_key", "source_id", "predicate", "target_id"])
    op.create_index("ix_graph_fact_target", "graph_facts", ["scope_key", "target_id"])
    op.create_index("ix_graph_fact_context", "graph_facts", ["scope_key", "context_id"])
    op.create_table(
        "graph_fact_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fact_id", sa.String(64), sa.ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("fact_id", "source_kind", "source_ref", name="uq_graph_fact_source"),
    )
    op.create_index("ix_graph_fact_source_ref", "graph_fact_sources", ["source_kind", "source_ref"])
    op.create_table(
        "graph_fact_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("from_fact_id", sa.String(64), sa.ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("predicate", sa.String(64), nullable=False),
        sa.Column("to_fact_id", sa.String(64), sa.ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("from_fact_id", "predicate", "to_fact_id", name="uq_graph_fact_relation"),
    )
    if op.get_bind().dialect.name == "postgresql":
        # SQL text search is an index, not part of the graph's identity.
        op.execute("CREATE INDEX ix_graph_fact_fts ON graph_facts USING gin "
                   "(to_tsvector('simple', fact_text))")
        for table in ("graph_nodes", "graph_identifiers", "graph_facts", "graph_fact_sources", "graph_fact_relations"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ("graph_fact_relations", "graph_fact_sources", "graph_facts", "graph_identifiers", "graph_nodes"):
        op.drop_table(table)
