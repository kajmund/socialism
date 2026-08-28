"""Persona/Population kind discriminators + customer_id on jobs and reports.

Revision ID: 036_persona_population_kind_job_report_customer
Revises: 035_merge_dd_and_scoping_heads
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036_persona_population_kind_job_report_customer"
down_revision: Union[str, Sequence[str], None] = "035_merge_dd_and_scoping_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OS_DEFAULT_CUSTOMER_ID = 1


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "personas",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="persona",
        ),
    )
    with op.batch_alter_table("personas") as batch_op:
        batch_op.alter_column("age", nullable=True)

    op.add_column(
        "populations",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="persona",
        ),
    )
    op.add_column(
        "population_members",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="persona",
        ),
    )

    op.add_column("jobs", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("customer_id", sa.Integer(), nullable=True))

    conn.execute(sa.text(f"UPDATE jobs SET customer_id = {_OS_DEFAULT_CUSTOMER_ID}"))
    conn.execute(sa.text(f"UPDATE reports SET customer_id = {_OS_DEFAULT_CUSTOMER_ID}"))

    conn.execute(
        sa.text(
            """
            UPDATE jobs
            SET customer_id = (
                SELECT p.customer_id
                FROM runs r
                JOIN projekt p ON r.project_id = p.id
                WHERE r.id = CAST(json_extract(jobs.request, '$.run_id') AS INTEGER)
            )
            WHERE jobs.kind = 'run_simulate'
              AND json_extract(jobs.request, '$.run_id') IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE jobs
            SET customer_id = (
                SELECT dc.customer_id
                FROM panel_sessions ps
                JOIN dd_campaigns dc ON ps.campaign_id = dc.id
                WHERE ps.job_id = jobs.id
            )
            WHERE jobs.kind = 'panel_session_run'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE reports
            SET customer_id = (
                SELECT dc.customer_id
                FROM panel_sessions ps
                JOIN dd_campaigns dc ON ps.campaign_id = dc.id
                WHERE ps.id = json_extract(reports.sources, '$[0].session_id')
            )
            WHERE reports.mode = 'dd'
              AND json_extract(reports.sources, '$[0].session_id') IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE reports
            SET customer_id = (
                SELECT p.customer_id
                FROM runs r
                JOIN projekt p ON r.project_id = p.id
                WHERE r.id = CAST(json_extract(reports.sources, '$[0].run_id') AS INTEGER)
            )
            WHERE reports.mode != 'dd'
              AND json_extract(reports.sources, '$[0].run_id') IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE jobs
            SET customer_id = (
                SELECT r.customer_id
                FROM reports r
                WHERE r.id = json_extract(jobs.request, '$.report_id')
            )
            WHERE jobs.kind = 'report_generate'
              AND json_extract(jobs.request, '$.report_id') IS NOT NULL
            """
        )
    )

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("customer_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_jobs_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_jobs_customer_id", ["customer_id"], unique=False)

    with op.batch_alter_table("reports") as batch_op:
        batch_op.alter_column("customer_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_reports_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_reports_customer_id", ["customer_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_index("ix_reports_customer_id")
        batch_op.drop_constraint("fk_reports_customer_id_kunder", type_="foreignkey")
        batch_op.drop_column("customer_id")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_customer_id")
        batch_op.drop_constraint("fk_jobs_customer_id_kunder", type_="foreignkey")
        batch_op.drop_column("customer_id")

    op.drop_column("population_members", "kind")
    op.drop_column("populations", "kind")
    with op.batch_alter_table("personas") as batch_op:
        batch_op.drop_column("kind")
        batch_op.alter_column("age", nullable=False)
