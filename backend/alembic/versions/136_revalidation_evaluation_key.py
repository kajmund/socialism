"""Recognize the deployed research migration head.

The production database was stamped with this revision by a parallel research
branch whose migration files were never merged. Its schema also contains the
source-independent claim changes from 125/126. Main's linear chain places this
compatibility marker after Graph v2 revision 128; the next migration reconciles
the deployed schema without replaying destructive claim changes.

The research branch's question-tree tables are not part of the current main
application schema. This compatibility marker does not manufacture them on a
fresh install; they remain on existing databases and are left untouched.
"""

revision = "136_revalidation_evaluation_key"
down_revision = "128_graph_ingest_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
