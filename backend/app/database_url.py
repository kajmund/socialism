def normalize_database_url(value: object) -> str:
    """Normalize supported PostgreSQL URLs to SQLAlchemy's psycopg driver."""
    url = str(value).strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url
