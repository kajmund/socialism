"""Owner connection for schema migrations, separate from runtime credentials."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.database_url import normalize_database_url


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    migration_database_url: str

    @field_validator("migration_database_url", mode="before")
    @classmethod
    def normalize_url(cls, value: object) -> str:
        if not value or not str(value).strip():
            raise ValueError("MIGRATION_DATABASE_URL must contain the database owner's connection URL")
        return normalize_database_url(value)
