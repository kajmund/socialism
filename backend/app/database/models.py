from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base


class Kund(Base):
    """Customer (tenant) — hardest scoping level for library data."""

    __tablename__ = "kunder"

    organization_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    available_modules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    product: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
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

    projekt: Mapped[list["Projekt"]] = relationship(
        back_populates="kund",
        cascade="all, delete-orphan",
    )
    personas: Mapped[list["Persona"]] = relationship(back_populates="kund")
    configurations: Mapped[list["Configuration"]] = relationship(back_populates="kund")
    dd_campaigns: Mapped[list["DdCampaign"]] = relationship(back_populates="kund")
    jobs: Mapped[list["Job"]] = relationship(back_populates="kund")
    reports: Mapped[list["Report"]] = relationship(back_populates="kund")
    prompt_overrides: Mapped[list["PromptOverride"]] = relationship(back_populates="kund")
    user_accounts: Mapped[list["UserAccount"]] = relationship(back_populates="kund")
    populations: Mapped[list["Population"]] = relationship(back_populates="kund")
    expert_profiles: Mapped[list["PanelExpertProfile"]] = relationship(back_populates="kund")
    execution_runs: Mapped[list["ExecutionRun"]] = relationship(back_populates="kund")


class UserAccount(Base):
    """Roll + kund-koppling för en Supabase-autentiserad användare."""

    __tablename__ = "user_accounts"

    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Supabase auth.users.id
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "admin" | "user" | "bolag"
    kund_id: Mapped[int | None] = mapped_column(
        ForeignKey("kunder.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    kund: Mapped[Kund | None] = relationship(back_populates="user_accounts")


class Projekt(Base):
    """Project grouping within a customer (soft scope for runs, messages, grunddata)."""

    __tablename__ = "projekt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
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

    kund: Mapped[Kund] = relationship(back_populates="projekt")
    runs: Mapped[list["Run"]] = relationship(back_populates="projekt")
    messages: Mapped[list["Message"]] = relationship(back_populates="projekt")

    __table_args__ = (UniqueConstraint("customer_id", "slug", name="uq_projekt_customer_slug"),)


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="persona", server_default="persona"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occ: Mapped[str] = mapped_column(String(255), nullable=False)
    district: Mapped[str] = mapped_column(String(255), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="manuell")
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    avatar_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    kund: Mapped[Kund] = relationship(back_populates="personas")
    memberships: Mapped[list["PopulationMember"]] = relationship(
        back_populates="persona",
        cascade="all, delete-orphan",
    )


class Population(Base):
    __tablename__ = "populations"
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_populations_customer_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="persona", server_default="persona"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
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

    kund: Mapped["Kund"] = relationship(back_populates="populations")
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
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="persona", server_default="persona"
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
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projekt.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    live_progress_main: Mapped[list | None] = mapped_column(JSON, nullable=True)
    live_progress_a: Mapped[list | None] = mapped_column(JSON, nullable=True)
    live_progress_b: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    population: Mapped[Population] = relationship(back_populates="runs")
    projekt: Mapped["Projekt"] = relationship(back_populates="runs")


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
    # SHA256 of an attached image in the image cache (vision chat turns).
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    # Run-scoped interview user turns: who asked (doctor via Spinndoktor tools vs human in UI).
    asked_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sme_expert_turn_request_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("sme_expert_turns.request_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class SmePanelMessage(Base):
    """One message in a customer-scoped SME expert-panel thread."""

    __tablename__ = "sme_panel_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    persona_id: Mapped[str | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SmeReadCursor(Base):
    """Per-user last-read message for an SME expert or panel thread."""

    __tablename__ = "sme_read_cursors"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "thread_type",
            "thread_id",
            name="uq_sme_read_cursors_user_thread",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_type: Mapped[str] = mapped_column(String(16), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_read_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SmePanelTurnLease(Base):
    """Per-panel lease so concurrent workers serialize SME panel turns."""

    __tablename__ = "sme_panel_turn_leases"

    panel_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SmeExpertTurn(Base):
    """Durable SME expert-chat turn keyed by the client's request_id."""

    __tablename__ = "sme_expert_turns"
    __table_args__ = (
        Index("ix_sme_expert_turns_user_persona", "user_id", "persona_id"),
    )

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona_id: Mapped[str] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="accepted")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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


class Message(Base):
    """Campaign message library (post / news) — not persona chat transcripts."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projekt.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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

    projekt: Mapped["Projekt"] = relationship(back_populates="messages")


class Configuration(Base):
    """Named prompt + grunddata configuration: language, prompts map, catalog lists."""

    __tablename__ = "configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    prompts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Softmax temperature for report SSR (tone/style). Lower = sharper label shares.
    ssr_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    # Per-locale tone/style anchor set ids: {"sv": {"tone": 1, "style": 2}, "en": {...}}
    anchor_sets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Snabbrapport verdict / diff / recommendation thresholds (see report/thresholds.py).
    report_thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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

    kund: Mapped[Kund] = relationship(back_populates="configurations")
    catalog_lists: Mapped[list["CatalogList"]] = relationship(
        back_populates="configuration",
        cascade="all, delete-orphan",
    )


class SsrLabelVocabulary(Base):
    """Global tone/style label vocabulary shared across anchor sets of a kind+locale."""

    __tablename__ = "ssr_label_vocabularies"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    locale: Mapped[str] = mapped_column(String(8), primary_key=True)
    # Ordered list of {"key": str, "label": str}.
    entries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
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
    misclassification_flags: Mapped[list["SsrMisclassificationFlag"]] = relationship(
        back_populates="anchor_set",
        cascade="all, delete-orphan",
        order_by="SsrMisclassificationFlag.id",
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


class SsrMisclassificationFlag(Base):
    """Operator flag: SSR predicted label disagrees with expected label."""

    __tablename__ = "ssr_misclassification_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anchor_set_id: Mapped[int] = mapped_column(
        ForeignKey("ssr_anchor_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_label: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_label: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    pool_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("ssr_anchor_pool_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    anchor_set: Mapped["SsrAnchorSet"] = relationship(back_populates="misclassification_flags")


class CatalogList(Base):
    """Editable master-data option lists scoped to a configuration."""

    __tablename__ = "catalog_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    configuration_id: Mapped[int] = mapped_column(
        ForeignKey("configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projekt.id", ondelete="RESTRICT"),
        nullable=True,
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
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    kund: Mapped[Kund] = relationship(back_populates="jobs")


class Report(Base):
    """Generated HTML simulation report (one or more run attempts)."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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

    kund: Mapped[Kund] = relationship(back_populates="reports")


class StoredObject(Base):
    """Metadata for an object in the kund+module Supabase S3 bucket."""

    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_stored_objects_bucket_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("dd_campaigns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    report_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    knowledge_status: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    knowledge_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    folder_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("underlag_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UnderlagFolder(Base):
    """Personal folder for underlag files (owner-scoped, per module)."""

    __tablename__ = "underlag_folders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("underlag_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class RattsunderlagSession(Base):
    """Saved rättsunderlag körning — draft, research job, and result links."""

    __tablename__ = "rattsunderlag_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    fraga: Mapped[str] = mapped_column(Text, nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="sv")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    job_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    report_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    underlag_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("stored_objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class SpindoctorMessage(Base):
    """Spinndoktor chat transcript scoped to one report."""

    __tablename__ = "spindoctor_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SpindoctorWidget(Base):
    """Spinndoktor board widget scoped to one report."""

    __tablename__ = "spindoctor_widgets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    pos_x: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ReportVerdictCalibration(Base):
    """Operator judgment: does the report recommendation match the whole report?"""

    __tablename__ = "report_verdict_calibrations"

    report_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    matches: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class DdCampaign(Base):
    """DD module campaign (M&A sourcing + panel) — phase 0 persistence."""

    __tablename__ = "dd_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False, default="dd", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_candidate_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expert_role_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expert_panel_id: Mapped[int | None] = mapped_column(
        ForeignKey("populations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    panel_assignments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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

    kund: Mapped[Kund] = relationship(back_populates="dd_campaigns")


class DdCandidateRun(Base):
    """Links a campaign candidate to its panel session and DD report."""

    __tablename__ = "dd_candidate_runs"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "candidate_id",
            name="uq_dd_candidate_runs_campaign_candidate",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("dd_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    panel_session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("panel_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    report_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    research: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    research_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


class PanelSession(Base):
    """Panel engine session — generic_panel and future protocols."""

    __tablename__ = "panel_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="generic_panel")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    transcript: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scratchpads: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    panel_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("populations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("projekt.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # DD-specific extra — generic modules use project_id, not this.
    campaign_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("dd_campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class PanelSubQuestion(Base):
    """Modul-skopade bedömningsdimensioner för Expertpanel-motorn."""

    __tablename__ = "panel_sub_questions"
    __table_args__ = (
        UniqueConstraint("module", "key", name="uq_panel_sub_questions_module_key"),
        UniqueConstraint("module", "sort_order", name="uq_panel_sub_questions_module_sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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


class PanelExpertProfile(Base):
    """Per-customer expert catalog. One row per (customer, key); many modules."""

    __tablename__ = "panel_expert_profiles"
    __table_args__ = (
        UniqueConstraint("customer_id", "key", name="uq_panel_expert_profiles_customer_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    modules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kompetensomrade: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    radgivningsstil: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    yrkesbakgrund: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    professionell_anekdot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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

    kund: Mapped["Kund"] = relationship(back_populates="expert_profiles")


class PromptField(Base):
    """Catalog of prompt keys and defaults. One row per key; many modules."""

    __tablename__ = "prompt_fields"
    __table_args__ = (UniqueConstraint("key", name="uq_prompt_fields_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    modules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    label_sv: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    label_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hint_sv: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hint_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_sv: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_nb: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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

    overrides: Mapped[list["PromptOverride"]] = relationship(
        back_populates="prompt_field",
        cascade="all, delete-orphan",
    )


class PromptOverride(Base):
    """Sparse per-customer prompt text. One row per (customer, field, language)."""

    __tablename__ = "prompt_overrides"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "prompt_field_id",
            "language",
            name="uq_prompt_overrides_customer_field_language",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    prompt_field_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_fields.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
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

    kund: Mapped[Kund] = relationship(back_populates="prompt_overrides")
    prompt_field: Mapped[PromptField] = relationship(back_populates="overrides")


class ExpertgranskningResult(Base):
    """Incremental Word-review comment from word_paragraph_review."""

    __tablename__ = "expertgranskning_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    section_index: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    expert_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expert_namn: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    kommentar: Mapped[str] = mapped_column(Text, nullable=False)
    is_heading_suggestion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    is_rewrite_suggestion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    foreslagen_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class WordAction(Base):
    """Generic persisted Word document operation from a producer workflow."""

    __tablename__ = "word_actions"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "source_ordinal",
            name="uq_word_actions_source",
        ),
        Index("ix_word_actions_customer_job", "customer_id", "job_id"),
        Index("ix_word_actions_application_id", "application_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    anchor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    application_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    application_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    word_artifact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeDocumentRecord(Base):
    """Provider-neutral index: internal document_id → source location.

    Storage path (bucket/key) is not the canonical document id.
    """

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_id", name="uq_knowledge_documents_provider_external"
        ),
    )

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    module: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_bucket: Mapped[str | None] = mapped_column(String(63), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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


class DocumentKnowledgeItem(Base):
    """Mutable human-facing knowledge attached to one uploaded document."""

    __tablename__ = "document_knowledge_items"
    __table_args__ = (
        Index(
            "ix_document_knowledge_items_document_status",
            "source_object_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_object_id: Mapped[str] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_queries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    anchors: Mapped[list["DocumentKnowledgeAnchor"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="DocumentKnowledgeAnchor.ordinal",
    )
    revisions: Mapped[list["DocumentKnowledgeRevision"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="DocumentKnowledgeRevision.revision",
    )


class DocumentKnowledgeAnchor(Base):
    """A source region. v1 writes text anchors; the shape also supports visuals."""

    __tablename__ = "document_knowledge_anchors"
    __table_args__ = (
        UniqueConstraint("item_id", "ordinal", name="uq_document_knowledge_anchor_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("document_knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anchor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exact_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prefix_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suffix_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rects: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    item: Mapped[DocumentKnowledgeItem] = relationship(back_populates="anchors")


class DocumentKnowledgeRevision(Base):
    """Append-only audit snapshot for edits to document knowledge."""

    __tablename__ = "document_knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("item_id", "revision", name="uq_document_knowledge_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("document_knowledge_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    item: Mapped[DocumentKnowledgeItem] = relationship(back_populates="revisions")


class ExecutionRun(Base):
    """Generic work/investigation container (product: Run).

    Distinct from simulation ``Run`` / ``runs`` (körningar). Tables are
    ``execution_*`` so the two models cannot be confused.
    """

    __tablename__ = "execution_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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

    kund: Mapped[Kund] = relationship(back_populates="execution_runs")
    attempts: Mapped[list["ExecutionAttempt"]] = relationship(
        back_populates="run",
        foreign_keys="ExecutionAttempt.run_id",
    )
    evidence_sets: Mapped[list["EvidenceSet"]] = relationship(back_populates="run")


class EvidenceSet(Base):
    """Building, frozen, or failed knowledge snapshot scoped to one ExecutionRun."""

    __tablename__ = "evidence_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("execution_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_from_attempt_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="building")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    run: Mapped[ExecutionRun] = relationship(back_populates="evidence_sets")
    items: Mapped[list["EvidenceSetItem"]] = relationship(
        back_populates="evidence_set",
        cascade="all, delete-orphan",
    )


class ExecutionAttempt(Base):
    """One concrete execution of an ExecutionRun (product: Attempt)."""

    __tablename__ = "execution_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("execution_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parent_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    attempt_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    configuration_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    research_objective_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    research_plan_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    research_wave: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    research_stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_sets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    run: Mapped[ExecutionRun] = relationship(
        back_populates="attempts",
        foreign_keys=[run_id],
    )
    parent_attempt: Mapped["ExecutionAttempt | None"] = relationship(
        remote_side=[id],
        foreign_keys=[parent_attempt_id],
    )
    evidence_set: Mapped[EvidenceSet | None] = relationship(
        foreign_keys=[evidence_set_id],
    )
    result: Mapped["ExecutionAttemptResult | None"] = relationship(
        back_populates="attempt",
        uselist=False,
    )
    need_executions: Mapped[list["ResearchNeedExecution"]] = relationship(
        back_populates="attempt",
    )
    research_assessments: Mapped[list["ResearchAssessment"]] = relationship(
        back_populates="attempt",
    )
    runtime_needs: Mapped[list["ResearchRuntimeNeed"]] = relationship(
        back_populates="attempt",
    )
    research_completeness_passes: Mapped[list["ResearchCompletenessPass"]] = relationship(
        back_populates="attempt",
    )
    research_claim: Mapped["ExecutionResearchClaim | None"] = relationship(
        back_populates="attempt",
        uselist=False,
    )
    research_progress_events: Mapped[list["ResearchProgressEvent"]] = relationship(
        back_populates="attempt",
    )


class ExecutionResearchClaim(Base):
    """Lease for one Attempt's background research. Not a business status."""

    __tablename__ = "execution_research_claims"

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    start_request: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="research_claim")


class ResearchNeedExecution(Base):
    """Per-need lifecycle under one Attempt. Plan snapshot owns the payload."""

    __tablename__ = "research_need_executions"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "research_need_id",
            name="uq_research_need_executions_attempt_need",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_need_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="need_executions")


class ResearchRuntimeNeed(Base):
    """Initial or derived ResearchNeed payload under one Attempt.

    The frozen research_plan_snapshot stays the original plan. This table
    is the runtime inventory used for recovery, lineage, and follow-ups.
    """

    __tablename__ = "research_runtime_needs"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "research_need_id",
            name="uq_research_runtime_needs_attempt_need",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_need_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    why_needed: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    domains: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    modalities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="initial")
    wave_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_research_need_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_assessment_pass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_completeness_pass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_gap: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="runtime_needs")


class EvidenceSource(Base):
    """One canonical provider document, shared by all questions and attempts."""

    __tablename__ = "evidence_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_identity: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    passages: Mapped[list["EvidencePassage"]] = relationship(back_populates="source")


class EvidencePassage(Base):
    """Immutable content-addressed passage within a canonical source."""

    __tablename__ = "evidence_passages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source: Mapped[EvidenceSource] = relationship(back_populates="passages")


class EvidenceSetItemNeed(Base):
    """Many-to-many lineage from one stored passage to runtime needs."""

    __tablename__ = "evidence_set_item_needs"

    evidence_set_item_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_set_items.id", ondelete="CASCADE"), primary_key=True
    )
    research_need_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class EvidenceSetItem(Base):
    """Historical snapshot of evidence the model saw — not a live pointer."""

    __tablename__ = "evidence_set_items"
    __table_args__ = (
        UniqueConstraint(
            "evidence_set_id",
            "original_evidence_id",
            name="uq_evidence_set_items_set_original_evidence_id",
        ),
        UniqueConstraint(
            "evidence_set_id",
            "passage_id",
            name="uq_evidence_set_items_set_passage",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_set_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    research_need_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    passage_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_passages.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    original_evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    evidence_set: Mapped[EvidenceSet] = relationship(back_populates="items")
    passage: Mapped[EvidencePassage | None] = relationship(lazy="selectin")
    need_links: Mapped[list[EvidenceSetItemNeed]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    quality_assessments: Mapped[list["ResearchEvidenceQuality"]] = relationship(
        back_populates="evidence_set_item",
    )


class ResearchEvidenceQuality(Base):
    """Immutable per-item quality artifact. Does not mutate EvidenceSet contents."""

    __tablename__ = "research_evidence_quality"
    __table_args__ = (
        UniqueConstraint(
            "evidence_set_item_id",
            "scoring_policy_version",
            "model_identity_key",
            name="uq_research_evidence_quality_item_policy_model",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_set_item_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_set_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_set_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_sets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scoring_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)
    relevance: Mapped[str] = mapped_column(String(32), nullable=False)
    currentness: Mapped[str] = mapped_column(String(32), nullable=False)
    source_nature: Mapped[str] = mapped_column(String(32), nullable=False)
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    independence_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    independent_source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    declared_signals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    evidence_set_item: Mapped[EvidenceSetItem] = relationship(back_populates="quality_assessments")


class ExecutionAttemptResult(Base):
    """Historical method output for one ExecutionAttempt (v1: generic_panel)."""

    __tablename__ = "execution_attempt_results"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_execution_attempt_results_attempt_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    panel_session_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("panel_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="result")


class ResearchAssessment(Base):
    """Persisted evidence-sufficiency judgment for one Attempt research pass."""

    __tablename__ = "research_assessments"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "assessment_pass",
            name="uq_research_assessments_attempt_pass",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_set_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_sets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assessment_pass: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    need_assessments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gaps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contradictions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    considered_evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="research_assessments")


class ResearchCompletenessPass(Base):
    """Persisted global-completeness judgment for one Attempt pass."""

    __tablename__ = "research_completeness_passes"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "completeness_pass",
            name="uq_research_completeness_passes_attempt_pass",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_set_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_sets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    completeness_pass: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    missing_questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    considered_evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    considered_question_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    question_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="research_completeness_passes")


class KnowledgeQuestionRow(Base):
    """Persistent canonical question. Not a runtime ResearchNeed."""

    __tablename__ = "knowledge_questions"
    __table_args__ = (
        UniqueConstraint(
            "namespace",
            "identity_key",
            name="uq_knowledge_questions_namespace_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    answers: Mapped[list["KnowledgeQuestionEvidenceLink"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
    )


class KnowledgeQuestionEvidenceLink(Base):
    """ANSWERED_BY / BESVARAS_AV reference. Not a document copy."""

    __tablename__ = "knowledge_question_evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "evidence_ref",
            name="uq_knowledge_question_evidence_ref",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passage_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_passages.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    evidence_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="ANSWERED_BY")
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="tenant")
    source_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

    question: Mapped[KnowledgeQuestionRow] = relationship(back_populates="answers")
    passage: Mapped[EvidencePassage | None] = relationship(lazy="selectin")


class ExpertKnowledgeReceipt(Base):
    """An expert remembers receiving frozen evidence for a canonical question."""

    __tablename__ = "expert_knowledge_receipts"
    __table_args__ = (
        UniqueConstraint(
            "expert_id",
            "knowledge_question_id",
            "source_attempt_id",
            "role",
            name="uq_expert_knowledge_receipt_lineage",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    expert_id: Mapped[str] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_question_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_question_id: Mapped[str] = mapped_column(
        ForeignKey("research_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_set_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_sets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SpecificQuestion(Base):
    """Context-bound user or review question that can require several general questions."""

    __tablename__ = "specific_questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("execution_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ResearchQuestion(Base):
    """One canonical general question participating in an Attempt's question DAG."""

    __tablename__ = "research_questions"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "specific_question_id",
            "knowledge_question_id",
            name="uq_research_questions_attempt_specific_knowledge",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    specific_question_id: Mapped[str] = mapped_column(
        ForeignKey("specific_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    knowledge_question_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    runtime_need_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    why_needed: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="initial")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ResearchQuestionExpert(Base):
    """Expert lineage: who raised a question and who is responsible for it."""

    __tablename__ = "research_question_experts"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "expert_id",
            "role",
            name="uq_research_question_experts_question_expert_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("research_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expert_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResearchQuestionDependency(Base):
    """Directed edge: question waits for depends_on_question."""

    __tablename__ = "research_question_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "depends_on_question_id",
            name="uq_research_question_dependencies_edge",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("research_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    depends_on_question_id: Mapped[str] = mapped_column(
        ForeignKey("research_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResearchProgressEvent(Base):
    """Audit/projection of a persisted research-domain transition for one Attempt."""

    __tablename__ = "research_progress_events"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "sequence",
            name="uq_research_progress_events_attempt_sequence",
        ),
        UniqueConstraint(
            "attempt_id",
            "idempotency_key",
            name="uq_research_progress_events_attempt_key",
        ),
        Index(
            "ix_research_progress_events_attempt_sequence",
            "attempt_id",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[ExecutionAttempt] = relationship(back_populates="research_progress_events")


class LlmRuntimeSettings(Base):
    """Singleton row for admin-selected chat LLM profile + sampling params."""

    __tablename__ = "llm_runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=8192)
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ActorContextProposal(Base):
    """Exact, user-confirmed profile edits; model tools cannot approve these."""

    __tablename__ = "actor_context_proposals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    target_label: Mapped[str] = mapped_column(String(255), nullable=False)
    changes: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
