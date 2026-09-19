import os
import subprocess
import sys
from pathlib import Path

from app.config import Settings
from app.database_url import normalize_database_url

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_normalizes_supabase_postgres_urls_for_psycopg() -> None:
    assert (
        Settings.normalize_database_url("postgres://user:pass@example.test:5432/postgres")
        == "postgresql+psycopg://user:pass@example.test:5432/postgres"
    )
    assert (
        Settings.normalize_database_url(
            "postgresql://user:pass@example.test:5432/postgres"
        )
        == "postgresql+psycopg://user:pass@example.test:5432/postgres"
    )


def test_preserves_explicit_database_driver() -> None:
    url = "postgresql+psycopg://user:pass@example.test:5432/postgres"
    assert Settings.normalize_database_url(url) == url


def test_application_database_url_has_no_sqlite_fallback() -> None:
    assert Settings.model_fields["database_url"].is_required()


def test_shared_normalizer_does_not_require_application_settings() -> None:
    assert (
        normalize_database_url("postgresql://user:pass@example.test/postgres")
        == "postgresql+psycopg://user:pass@example.test/postgres"
    )


def test_alembic_only_requires_database_configuration() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": "sqlite:///:memory:",
            "CEREBRAS_API_KEY": "",
            "OPENAI_API_KEY": "",
            "SUPABASE_URL": "",
            "SUPABASE_SERVICE_ROLE_KEY": "",
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=_BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
