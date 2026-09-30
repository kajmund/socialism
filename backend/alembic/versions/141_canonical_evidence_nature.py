"""Declare the evidence nature of persisted lagen.nu documents."""

import re

import sqlalchemy as sa
from alembic import op

revision = "141_canonical_evidence_nature"
down_revision = "140_graph_embedding_cache"
branch_labels = None
depends_on = None

DOCUMENTS = sa.table(
    "canonical_documents",
    sa.column("id", sa.String()),
    sa.column("source_type", sa.String()),
    sa.column("canonical_uri", sa.String()),
    sa.column("extra", sa.JSON()),
)


def _nature(uri: str) -> str:
    # These are canonical publisher namespaces, not a runtime retrieval fallback.
    path = uri.removeprefix("https://lagen.nu/")
    if path == uri:
        raise ValueError(f"Noncanonical lagen.nu document: {uri!r}")
    if re.fullmatch(r"\d{4}:\d+", path):
        return "swedish_law"
    if re.fullmatch(r"dom/[^/]+/.+", path):
        return "swedish_case_law"
    if re.fullmatch(r"(?:prop|sou|ds|bet|rskr)/.+", path):
        return "swedish_preparatory_works"
    raise ValueError(f"Cannot declare evidence nature for lagen.nu document: {uri!r}")


def upgrade() -> None:
    connection = op.get_bind()
    rows = (
        connection.execute(sa.select(DOCUMENTS).where(DOCUMENTS.c.source_type == "lagen_nu"))
        .mappings()
        .all()
    )
    updates = []
    for row in rows:
        nature = _nature(row["canonical_uri"])
        extra = dict(row["extra"] or {})
        declared = extra.get("evidence_nature")
        if declared is not None and declared != nature:
            raise ValueError(f"Conflicting evidence nature for document {row['id']}")
        updates.append((row["id"], {**extra, "evidence_nature": nature}))
    # Validate every document before changing any row.
    for document_id, extra in updates:
        connection.execute(
            DOCUMENTS.update().where(DOCUMENTS.c.id == document_id).values(extra=extra)
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = (
        connection.execute(sa.select(DOCUMENTS).where(DOCUMENTS.c.source_type == "lagen_nu"))
        .mappings()
        .all()
    )
    for row in rows:
        extra = dict(row["extra"] or {})
        extra.pop("evidence_nature", None)
        connection.execute(
            DOCUMENTS.update().where(DOCUMENTS.c.id == row["id"]).values(extra=extra)
        )
