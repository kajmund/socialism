"""Exercise the deployed Alembic marker alongside the Graph v2 branch."""

import sqlite3
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_deployed_research_marker_upgrades_without_replaying_claim_migrations(
    tmp_path: Path, monkeypatch,
) -> None:
    db = tmp_path / "deployed.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    app_logger = logging.getLogger("app.research.observability")

    command.upgrade(config, "126_knowledge_claim_source_independence")
    assert not app_logger.disabled
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TABLE knowledge_answer_reviews")
        connection.execute("CREATE TABLE research_question_nodes (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO research_question_nodes VALUES ('preserved')")
        connection.execute(
            "UPDATE alembic_version SET version_num = ?",
            ("136_revalidation_evaluation_key",),
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert not app_logger.disabled
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (ScriptDirectory.from_config(config).get_current_head(),)
        ]
        assert connection.execute("SELECT id FROM research_question_nodes").fetchall() == [
            ("preserved",)
        ]
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "graph_nodes", "graph_facts", "graph_ingest_work", "knowledge_answer_reviews",
            "graph_fact_question_dependencies", "graph_embedding_cache",
            "shared_text_chunks",
        } <= names
        assert "graph_fact_revalidations" not in names
        assert "graph_question_revalidation_work" not in names


def _table_names(db: Path) -> set[str]:
    with sqlite3.connect(db) as connection:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def test_head_drops_unused_graph_revalidation_queues(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "revalidation-drop.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "e8c2f4a1b6d0")
    before = _table_names(db)
    assert {
        "graph_fact_revalidations",
        "graph_question_revalidation_work",
        "graph_fact_question_dependencies",
        "graph_ingest_work",
        "knowledge_answer_reviews",
    } <= before

    command.upgrade(config, "head")
    after = _table_names(db)
    assert "graph_fact_revalidations" not in after
    assert "graph_question_revalidation_work" not in after
    assert {
        "graph_fact_question_dependencies",
        "graph_ingest_work",
        "knowledge_answer_reviews",
    } <= after
    assert ScriptDirectory.from_config(config).get_current_head() == (
        "151_workspace_chat_documents"
    )
