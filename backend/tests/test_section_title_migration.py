"""Changing section titles to TEXT preserves content and rejects lossy rollback."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_section_title_migration_preserves_content_and_guards_downgrade(monkeypatch):
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/668bd23eb2df_preserve_full_document_section_titles.py"
    )
    spec = importlib.util.spec_from_file_location("section_title_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE document_sections (id INTEGER PRIMARY KEY, title VARCHAR(512))")
        )
        connection.execute(sa.text("INSERT INTO document_sections VALUES (1, 'Original')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert isinstance(
            sa.inspect(connection).get_columns("document_sections")[1]["type"], sa.Text
        )
        assert connection.scalar(sa.text("SELECT title FROM document_sections")) == "Original"
        title = "Åäö " * 300
        connection.execute(sa.text("UPDATE document_sections SET title=:title"), {"title": title})
        with pytest.raises(ValueError, match="without losing"):
            migration.downgrade()
        assert connection.scalar(sa.text("SELECT title FROM document_sections")) == title
        connection.execute(sa.text("UPDATE document_sections SET title='Short'"))
        migration.downgrade()
        assert sa.inspect(connection).get_columns("document_sections")[1]["type"].length == 512
    engine.dispose()
