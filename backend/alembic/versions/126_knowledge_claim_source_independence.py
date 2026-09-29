"""Drop claim-level document ownership. Provenance is TextUnit support.

Revision ID: 126_knowledge_claim_source_independence
Revises: 125_knowledge_persistence_gate
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "126_knowledge_claim_source_independence"
down_revision: str | Sequence[str] | None = "125_knowledge_persistence_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_COLUMNS = frozenset({"document_id", "document_version_id"})


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for index in inspector.get_indexes("knowledge_claims"):
        name = index.get("name")
        columns = set(index.get("column_names") or ())
        if name and _SOURCE_COLUMNS.intersection(columns):
            op.drop_index(name, table_name="knowledge_claims")
    for fk in inspector.get_foreign_keys("knowledge_claims"):
        name = fk.get("name")
        columns = set(fk.get("constrained_columns") or ())
        if name and _SOURCE_COLUMNS.intersection(columns):
            op.drop_constraint(name, "knowledge_claims", type_="foreignkey")
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.drop_column("document_id")
        batch.drop_column("document_version_id")


def downgrade() -> None:
    raise NotImplementedError("source-independent claims are not reversible")
