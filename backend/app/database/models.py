from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    occ: Mapped[str] = mapped_column(String(255), nullable=False)
    district: Mapped[str] = mapped_column(String(255), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="manuell")
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    memberships: Mapped[list["PopulationMember"]] = relationship(
        back_populates="persona",
        cascade="all, delete-orphan",
    )


class Population(Base):
    __tablename__ = "populations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    versions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fingerprint: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fingerprint_inferred: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    recipe: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    members: Mapped[list["PopulationMember"]] = relationship(
        back_populates="population",
        cascade="all, delete-orphan",
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="population")


class PopulationMember(Base):
    __tablename__ = "population_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_id: Mapped[str | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    initials: Mapped[str] = mapped_column(String(8), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    occ: Mapped[str] = mapped_column(String(255), nullable=False)
    district: Mapped[str] = mapped_column(String(255), nullable=False)
    trait: Mapped[str] = mapped_column(Text, nullable=False, default="")
    age_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lean_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    district_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    population: Mapped[Population] = relationship(back_populates="members")
    persona: Mapped[Persona | None] = relationship(back_populates="memberships")


class PopulationGeneration(Base):
    __tablename__ = "population_generations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recipe: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[list] = mapped_column(JSON, nullable=False)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False)
    qa_warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    seed: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    main_ticks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    branch: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    oasis_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    population: Mapped[Population] = relationship(back_populates="runs")


class HelpMessage(Base):
    """In-app help chat transcript (scoped by browser session id)."""

    __tablename__ = "help_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FeedbackItem(Base):
    """Bugs, ideas, and opinions collected from help chat (and optionally admin)."""

    __tablename__ = "feedback_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="help")
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    view_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PersonaMessage(Base):
    __tablename__ = "persona_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[str] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # When set together: post-hoc interview scoped to a run attempt/variant/tick.
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    through_tick_index: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Message(Base):
    """Campaign message library (post / news) — not persona chat transcripts."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Configuration(Base):
    """Named prompt + grunddata configuration: language, prompts map, catalog lists."""

    __tablename__ = "configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    prompts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Softmax temperature for report SSR (tone/style). Lower = sharper label shares.
    ssr_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    # Per-locale tone/style anchor set ids: {"sv": {"tone": 1, "style": 2}, "en": {...}}
    anchor_sets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    catalog_lists: Mapped[list["CatalogList"]] = relationship(
        back_populates="configuration",
        cascade="all, delete-orphan",
    )


class SsrAnchorSet(Base):
    """Versioned SSR anchor library entry (tone Likert or style categories)."""

    __tablename__ = "ssr_anchor_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    labels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    statements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    # Bumped on append/remove to ssr_anchor_pool_items; invalidates centroid cache.
    pool_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calibration_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    calibration_pool_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calibration_n_at_test: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calibration_publish_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    calibration_items: Mapped[list["SsrAnchorCalibrationItem"]] = relationship(
        back_populates="anchor_set",
        cascade="all, delete-orphan",
        order_by="SsrAnchorCalibrationItem.sort_order",
    )
    pool_items: Mapped[list["SsrAnchorPoolItem"]] = relationship(
        back_populates="anchor_set",
        cascade="all, delete-orphan",
        order_by="SsrAnchorPoolItem.id",
    )


class SsrAnchorCalibrationItem(Base):
    """Human-labeled sample text for anchor set calibration / test bench."""

    __tablename__ = "ssr_anchor_calibration_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anchor_set_id: Mapped[int] = mapped_column(
        ForeignKey("ssr_anchor_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    human_label: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    anchor_set: Mapped["SsrAnchorSet"] = relationship(back_populates="calibration_items")


class SsrAnchorPoolItem(Base):
    """Simulated-language anchor example appended to a published anchor set."""

    __tablename__ = "ssr_anchor_pool_items"
    __table_args__ = (
        UniqueConstraint(
            "anchor_set_id",
            "label",
            "text",
            name="uq_ssr_anchor_pool_set_label_text",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anchor_set_id: Mapped[int] = mapped_column(
        ForeignKey("ssr_anchor_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    anchor_set: Mapped["SsrAnchorSet"] = relationship(back_populates="pool_items")


class CatalogList(Base):
    """Editable master-data option lists scoped to a configuration."""

    __tablename__ = "catalog_lists"
    __table_args__ = (
        UniqueConstraint("configuration_id", "key", name="uq_catalog_lists_config_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    configuration_id: Mapped[int] = mapped_column(
        ForeignKey("configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    configuration: Mapped["Configuration"] = relationship(back_populates="catalog_lists")


class Job(Base):
    """Background work units (e.g. population generation)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    request: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Report(Base):
    """Generated HTML simulation report (one or more run attempts)."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="sv")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="quick")
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    html_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    slots_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
