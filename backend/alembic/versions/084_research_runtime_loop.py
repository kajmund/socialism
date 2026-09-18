"""Runtime research loop: derived needs, wave, stop reason, follow-up prompt.

Revision ID: 084_research_runtime_loop
Revises: 083_research_assessments
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "084_research_runtime_loop"
down_revision: Union[str, Sequence[str], None] = "083_research_assessments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_KEY = "research.followup.system"


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def upgrade() -> None:
    op.add_column(
        "execution_attempts",
        sa.Column("research_wave", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "execution_attempts",
        sa.Column("research_stop_reason", sa.String(length=32), nullable=True),
    )
    op.create_table(
        "research_runtime_needs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("research_need_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("why_needed", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.JSON(), nullable=False),
        sa.Column("source_types", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("wave_number", sa.Integer(), nullable=False),
        sa.Column("parent_research_need_id", sa.String(length=64), nullable=True),
        sa.Column("source_assessment_pass", sa.Integer(), nullable=True),
        sa.Column("source_gap", sa.Text(), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "research_need_id",
            name="uq_research_runtime_needs_attempt_need",
        ),
    )
    op.create_index(
        "ix_research_runtime_needs_attempt_id",
        "research_runtime_needs",
        ["attempt_id"],
    )

    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(
            key=_NEW_KEY
        )
    ).fetchone()
    if exists is not None:
        return
    field = _field(_NEW_KEY)
    labels = field["label"]
    hints = field["hint"]
    defaults = field["defaults"]
    conn.execute(
        sa.text(
            "INSERT INTO prompt_fields ("
            "key, modules, section, label_sv, label_en, hint_sv, hint_en, "
            "default_sv, default_en, default_nb, active"
            ") VALUES ("
            ":key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
            ":default_sv, :default_en, :default_nb, TRUE"
            ")"
        ).bindparams(
            sa.bindparam("modules", type_=sa.JSON()),
            key=_NEW_KEY,
            modules=modules_for_prompt_key(_NEW_KEY),
            section=field["section"],
            label_sv=labels["sv"],
            label_en=labels["en"],
            hint_sv=hints["sv"],
            hint_en=hints["en"],
            default_sv=defaults["sv"],
            default_en=defaults["en"],
            default_nb=defaults["nb"],
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(
            key=_NEW_KEY
        )
    ).fetchone()
    if field_id is not None:
        conn.execute(
            sa.text(
                "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
            ).bindparams(field_id=field_id[0])
        )
        conn.execute(
            sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(
                key=_NEW_KEY
            )
        )
    op.drop_index(
        "ix_research_runtime_needs_attempt_id",
        table_name="research_runtime_needs",
    )
    op.drop_table("research_runtime_needs")
    op.drop_column("execution_attempts", "research_stop_reason")
    op.drop_column("execution_attempts", "research_wave")
