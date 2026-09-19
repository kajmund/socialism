import pytest
from pydantic import ValidationError

from app.migration_config import MigrationSettings


def test_migrations_require_owner_connection_not_runtime_url(monkeypatch):
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:secret@localhost/postgres")
    with pytest.raises(ValidationError, match="migration_database_url") as error:
        MigrationSettings(_env_file=None)
    assert "secret" not in str(error.value)


def test_migration_url_normalizes_driver_and_preserves_encoded_password(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgres://owner:p%40ss@localhost/postgres")
    settings = MigrationSettings(_env_file=None)
    assert settings.migration_database_url == "postgresql+psycopg://owner:p%40ss@localhost/postgres"


def test_empty_migration_url_fails_clearly(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "")
    with pytest.raises(ValidationError, match="MIGRATION_DATABASE_URL"):
        MigrationSettings(_env_file=None)
