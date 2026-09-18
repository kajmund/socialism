from app.config import Settings


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
