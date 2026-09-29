"""Exercise the deployed Alembic marker alongside the Graph v2 branch."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_deployed_research_marker_upgrades_without_replaying_claim_migrations(
    tmp_path: Path, monkeypatch,
) -> None:
    db = tmp_path / "deployed.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "126_knowledge_claim_source_independence")
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
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("139_graph_question_revalidation_work",)
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
            "graph_fact_question_dependencies", "graph_fact_revalidations",
            "graph_question_revalidation_work",
        } <= names
