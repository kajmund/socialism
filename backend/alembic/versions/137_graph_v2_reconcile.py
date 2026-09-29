"""Reconcile deployed research marker with Graph v2.

The deployed database is stamped at 136 from a parallel branch and lacks the
Graph v2 tables on main's 127/128 chain. A fresh install already has these
tables. Create the missing complete Graph v2 set only on the deployed path,
then restore the absent TTL review table. Existing research rows stay untouched.
"""

from pathlib import Path
from runpy import run_path

import sqlalchemy as sa
from alembic import op

revision = "137_graph_v2_reconcile"
down_revision = "136_revalidation_evaluation_key"
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
    tables = set(inspector.get_table_names())
    graph_tables = {
        "graph_nodes", "graph_identifiers", "graph_facts", "graph_fact_sources",
        "graph_fact_relations", "graph_ingest_work",
    }
    present = graph_tables & tables
    if present and present != graph_tables:
        raise RuntimeError(f"Partially installed Graph v2 schema needs manual repair: {sorted(present)}")
    if not present:
        versions = Path(__file__).parent
        run_path(str(versions / "127_graph_v2.py"))["upgrade"]()
        run_path(str(versions / "128_graph_ingest_outbox.py"))["upgrade"]()
    if "knowledge_answer_reviews" in tables:
        return
    # This is the exact schema introduced by 124_knowledge_answer_review_ttl.
    migration = Path(__file__).with_name("124_knowledge_answer_review_ttl.py")
    run_path(str(migration))["upgrade"]()


def downgrade() -> None:
    # An existing installation may have had this table before the merge.
    pass
