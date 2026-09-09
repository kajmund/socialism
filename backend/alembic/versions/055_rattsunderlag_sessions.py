"""Rättsunderlag sessions for draft/config/result körningar.

Revision ID: 055_rattsunderlag_sessions
Revises: 054_retire_unused_prompt_fields
"""

from __future__ import annotations

import json
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055_rattsunderlag_sessions"
down_revision: Union[str, Sequence[str], None] = "054_retire_unused_prompt_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rattsunderlag_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=4000), nullable=False),
        sa.Column("fraga", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("report_id", sa.String(length=64), nullable=True),
        sa.Column("underlag_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["underlag_id"], ["stored_objects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rattsunderlag_sessions_customer_id"),
        "rattsunderlag_sessions",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rattsunderlag_sessions_job_id"),
        "rattsunderlag_sessions",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rattsunderlag_sessions_owner_user_id"),
        "rattsunderlag_sessions",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rattsunderlag_sessions_status"),
        "rattsunderlag_sessions",
        ["status"],
        unique=False,
    )

    conn = op.get_bind()
    jobs = conn.execute(
        sa.text(
            "SELECT id, customer_id, status, request, result, error, created_at, updated_at "
            "FROM jobs WHERE kind = 'rattsunderlag_research'"
        )
    ).mappings()
    insert = sa.text(
        "INSERT INTO rattsunderlag_sessions "
        "(id, customer_id, owner_user_id, title, fraga, locale, status, job_id, "
        "report_id, underlag_id, error, created_at, updated_at) "
        "VALUES (:id, :customer_id, :owner_user_id, :title, :fraga, :locale, :status, "
        ":job_id, :report_id, :underlag_id, :error, :created_at, :updated_at)"
    )
    for job in jobs:
        request = job["request"]
        result = job["result"]
        if isinstance(request, str):
            request = json.loads(request)
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(request, dict):
            request = {}
        if not isinstance(result, dict):
            result = {}
        owner = str(request.get("owner_user_id") or "")
        fraga = str(request.get("fraga") or "")
        if not owner or not fraga:
            continue
        locale = str(request.get("locale") or "sv")
        if locale not in {"sv", "en"}:
            locale = "sv"
        status = str(job["status"] or "succeeded")
        if status not in {"pending", "running", "succeeded", "failed"}:
            status = "succeeded"
        session_id = f"rus_{secrets.token_hex(8)}"
        report_id = result.get("report_id")
        underlag_id = result.get("underlag_id")
        conn.execute(
            insert,
            {
                "id": session_id,
                "customer_id": job["customer_id"],
                "owner_user_id": owner,
                "title": "",
                "fraga": fraga,
                "locale": locale,
                "status": status if owner and fraga else "failed",
                "job_id": job["id"],
                "report_id": report_id if isinstance(report_id, str) else None,
                "underlag_id": underlag_id if isinstance(underlag_id, str) else None,
                "error": job["error"],
                "created_at": job["created_at"],
                "updated_at": job["updated_at"],
            },
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_rattsunderlag_sessions_status"), table_name="rattsunderlag_sessions")
    op.drop_index(op.f("ix_rattsunderlag_sessions_owner_user_id"), table_name="rattsunderlag_sessions")
    op.drop_index(op.f("ix_rattsunderlag_sessions_job_id"), table_name="rattsunderlag_sessions")
    op.drop_index(op.f("ix_rattsunderlag_sessions_customer_id"), table_name="rattsunderlag_sessions")
    op.drop_table("rattsunderlag_sessions")
