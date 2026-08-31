import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

SimulationEngine = Literal["none", "oasis"]
PersonaGenerator = Literal["deepseek", "stub"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/opinionssimulator.db"
    allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    # HTTP timeout for DeepSeek calls (seconds). Prevents hung report jobs.
    deepseek_timeout_seconds: float = 60.0
    # stub = weighted random (tests only); deepseek = call DeepSeek
    persona_generator: PersonaGenerator = "deepseek"

    # OpenAI embeddings for SSR (separate from DeepSeek chat / CAMEL env mirror).
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-large"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_timeout_seconds: float = 60.0
    # OpenAI vision for playground image understanding (same API key as embeddings).
    vision_model: str = "gpt-4o-mini"
    vision_timeout_seconds: float = 60.0
    # Optional playground vision providers (validated when selected in UI).
    google_api_key: str = ""
    google_vision_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com"
    # Write-through cache for SSR anchor embeddings (memory + disk).
    embedding_cache_dir: str = "data/embedding_cache"
    # Budskap image bytes + vision captions keyed by SHA256.
    image_cache_dir: str = "data/image_cache"
    # OKF operator manuals for in-app help chat (empty = repo knowledge/manual).
    okf_manual_dir: str = ""

    # BolagsAPI remote MCP (DD company search). When empty, company tools use Allabolag.
    bolagsapi_api_key: str = ""
    bolagsapi_mcp_url: str = "https://mcp.bolagsapi.se/mcp"
    bolagsapi_cache_dir: str = "data/bolagsapi_cache"

    # Supabase Auth — JWT verify + Admin invite (service_role never goes to the SPA).
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_role_key: str = ""

    # none = status-only start; oasis = live CAMEL OASIS spike (optional dep group)
    simulation_engine: SimulationEngine = "none"
    # Cap overlapping run_simulate background jobs (A/B variants within one job
    # still run concurrently; this limits distinct körningar fighting for the API).
    max_concurrent_simulation_jobs: int = Field(default=2, ge=1, le=32)
    # Max concurrent LLM calls when generating personas in one population batch.
    # 1 = serial (debug); higher values overlap profile/anecdote waves.
    persona_generate_concurrency: int = Field(default=8, ge=1, le=32)
    # Rotating API log (empty = no file). Relative paths resolve from cwd.
    log_dir: str = "data/logs"
    log_max_bytes: int = Field(default=2_000_000, ge=1024)
    log_backup_count: int = Field(default=5, ge=1, le=50)
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def require_log_level(cls, value: str) -> str:
        name = value.strip().upper()
        if name not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return name

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("deepseek_api_key")
    @classmethod
    def require_deepseek_api_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError(
                "DEEPSEEK_API_KEY is required — set it in backend/.env "
                "(no heuristic/stub LLM fallback)"
            )
        return key

    @field_validator("openai_api_key")
    @classmethod
    def require_openai_api_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError(
                "OPENAI_API_KEY is required — set it in backend/.env "
                "(OpenAI embeddings for SSR; separate from DeepSeek chat)"
            )
        return key

    @field_validator("supabase_url")
    @classmethod
    def require_supabase_url(cls, value: str) -> str:
        url = value.strip()
        if not url:
            raise ValueError(
                "SUPABASE_URL is required — set it in backend/.env "
                "(Supabase project URL for Auth)"
            )
        return url

    @field_validator("supabase_jwt_secret")
    @classmethod
    def require_supabase_jwt_secret(cls, value: str) -> str:
        secret = value.strip()
        if not secret:
            raise ValueError(
                "SUPABASE_JWT_SECRET is required — set it in backend/.env "
                "(HS256 secret for verifying Supabase access tokens)"
            )
        return secret

    @field_validator("supabase_service_role_key")
    @classmethod
    def require_supabase_service_role_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError(
                "SUPABASE_SERVICE_ROLE_KEY is required — set it in backend/.env "
                "(backend-only; used for Admin invite API)"
            )
        return key

    def uses_llm_generator(self) -> bool:
        return self.persona_generator == "deepseek"

    @property
    def okf_manual_path(self) -> Path:
        override = self.okf_manual_dir.strip()
        if override:
            return Path(override)
        return Path(__file__).resolve().parents[2] / "knowledge" / "manual"

    def apply_oasis_env(self) -> None:
        """Mirror DeepSeek into env vars CAMEL reads (overwrite — not embeddings key)."""
        # Force DeepSeek for OASIS even when OPENAI_API_KEY is a real OpenAI key
        # used by settings.openai_api_key / the SSR embeddings client.
        os.environ["OPENAI_API_KEY"] = self.deepseek_api_key
        os.environ["OPENAI_COMPATIBLE_API_KEY"] = self.deepseek_api_key


settings = Settings()
