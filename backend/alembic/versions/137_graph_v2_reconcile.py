"""Join the deployed research marker and Graph v2 outbox.

Production already has the 125/126 claim schema but lacks the TTL review table
from the other migration branch. Restore that table only when absent, after both
graph revisions have run. Existing research tables and rows are untouched.
"""

from pathlib import Path
from runpy import run_path

import sqlalchemy as sa
from alembic import op

revision = "137_graph_v2_reconcile"
down_revision = ("128_graph_ingest_outbox", "136_revalidation_evaluation_key")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    claims = {column["name"] for column in inspector.get_columns("knowledge_claims")}
    if "identity_key" not in claims or {"document_id", "document_version_id"} & claims:
        raise RuntimeError("Deployed claim schema is not at source-independent revision 126")
    if "knowledge_observations" not in inspector.get_table_names():
        raise RuntimeError("Deployed knowledge_observations table is missing")
    if "knowledge_answer_reviews" in inspector.get_table_names():
        return
    # This is the exact schema introduced by 124_knowledge_answer_review_ttl.
    migration = Path(__file__).with_name("124_knowledge_answer_review_ttl.py")
    run_path(str(migration))["upgrade"]()


def downgrade() -> None:
    # An existing installation may have had this table before the merge.
    pass
