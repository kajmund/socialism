"""Portable property-graph records. SQL indexes are storage details, not identities."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("scope_key", "node_type", "identity_key", name="uq_graph_node_identity"),
        Index("ix_graph_node_name", "scope_key", "node_type", "normalized_name"),
        CheckConstraint("(scope_key = 'shared' AND customer_id IS NULL) OR "
                        "(scope_key = 'customer:' || customer_id AND customer_id IS NOT NULL)",
                        name="ck_graph_node_scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("kunder.id"), nullable=True)
    node_type: Mapped[str] = mapped_column(String(128), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphIdentifier(Base):
    __tablename__ = "graph_identifiers"
    __table_args__ = (
        UniqueConstraint("scope_key", "namespace", "identifier", name="uq_graph_identifier"),
        Index("ix_graph_identifier_node", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    identifier: Mapped[str] = mapped_column(String(512), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False)


class GraphFact(Base):
    __tablename__ = "graph_facts"
    __table_args__ = (
        UniqueConstraint("scope_key", "identity_key", name="uq_graph_fact_identity"),
        Index("ix_graph_fact_endpoints", "scope_key", "source_id", "predicate", "target_id"),
        Index("ix_graph_fact_target", "scope_key", "target_id"),
        Index("ix_graph_fact_context", "scope_key", "context_id"),
        CheckConstraint("(scope_key = 'shared' AND customer_id IS NULL) OR "
                        "(scope_key = 'customer:' || customer_id AND customer_id IS NOT NULL)",
                        name="ck_graph_fact_scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("kunder.id"), nullable=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"), nullable=False)
    context_id: Mapped[str | None] = mapped_column(ForeignKey("graph_nodes.id"), nullable=True)
    predicate: Mapped[str] = mapped_column(String(128), nullable=False)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurrence_key: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GraphFactSource(Base):
    __tablename__ = "graph_fact_sources"
    __table_args__ = (
        UniqueConstraint("fact_id", "source_kind", "source_ref", name="uq_graph_fact_source"),
        Index("ix_graph_fact_source_ref", "source_kind", "source_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphFactRelation(Base):
    __tablename__ = "graph_fact_relations"
    __table_args__ = (UniqueConstraint("from_fact_id", "predicate", "to_fact_id", name="uq_graph_fact_relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_fact_id: Mapped[str] = mapped_column(ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False)
    predicate: Mapped[str] = mapped_column(String(64), nullable=False)
    to_fact_id: Mapped[str] = mapped_column(ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False)


class GraphFactQuestionDependency(Base):
    """Question→fact dependency with the fact's exact supporting provenance."""

    __tablename__ = "graph_fact_question_dependencies"
    __table_args__ = (
        UniqueConstraint("question_node_id", "fact_id", name="uq_graph_fact_question_dependency"),
        Index("ix_graph_fact_question_dependency_fact", "fact_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    question_node_id: Mapped[str] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False,
    )
    fact_id: Mapped[str] = mapped_column(
        ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False,
    )
    relation: Mapped[str] = mapped_column(String(64), nullable=False, default="research.depends_on")
    provenance: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphFactRevalidation(Base):
    """Durable candidate work for facts supporting questions, never claim/event IDs."""

    __tablename__ = "graph_fact_revalidations"
    __table_args__ = (
        UniqueConstraint(
            "trigger_fact_id", "dependent_fact_id", "question_node_id",
            name="uq_graph_fact_revalidation_candidate",
        ),
        Index("ix_graph_fact_revalidation_pending", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_fact_id: Mapped[str] = mapped_column(
        ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False,
    )
    dependent_fact_id: Mapped[str] = mapped_column(
        ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False,
    )
    question_node_id: Mapped[str] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False,
    )
    trigger_provenance: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dependent_provenance: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphIngestWork(Base):
    __tablename__ = "graph_ingest_work"
    __table_args__ = (Index("ix_graph_ingest_pending", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("kunder.id"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
