from app.database.sqlite import (
    POSTGRES_MAX_OVERFLOW,
    POSTGRES_POOL_RECYCLE_SECONDS,
    POSTGRES_POOL_SIZE,
    async_engine_kwargs,
)

_POSTGRES = "postgresql+psycopg://user:pass@example.test/postgres"


def test_postgres_engine_kwargs_stay_below_session_pooler_cap():
    kwargs = async_engine_kwargs(_POSTGRES)
    assert kwargs["pool_size"] == POSTGRES_POOL_SIZE
    assert kwargs["max_overflow"] == POSTGRES_MAX_OVERFLOW
    assert kwargs["pool_size"] + kwargs["max_overflow"] < 15
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == POSTGRES_POOL_RECYCLE_SECONDS
    assert kwargs["pool_use_lifo"] is True


def test_postgres_engine_kwargs_keep_explicit_overrides():
    kwargs = async_engine_kwargs(_POSTGRES, pool_size=2, max_overflow=0)
    assert kwargs["pool_size"] == 2
    assert kwargs["max_overflow"] == 0


def test_sqlite_engine_kwargs_omit_postgres_pool():
    kwargs = async_engine_kwargs("sqlite+aiosqlite:///:memory:")
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "pool_recycle" not in kwargs
