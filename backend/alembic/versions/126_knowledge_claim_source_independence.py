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
    indexes = inspector.get_indexes("knowledge_claims")
    fks = inspector.get_foreign_keys("knowledge_claims")
    with op.batch_alter_table("knowledge_claims") as batch:
        for index in indexes:
            if _SOURCE_COLUMNS.intersection(index.get("column_names") or ()):
                batch.drop_index(index["name"])
        for fk in fks:
            if _SOURCE_COLUMNS.intersection(fk.get("constrained_columns") or ()):
                batch.drop_constraint(fk["name"], type_="foreignkey")
        batch.drop_column("document_id")
        batch.drop_column("document_version_id")


def downgrade() -> None:
    raise NotImplementedError("source-independent claims are not reversible")
