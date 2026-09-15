import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

EMBEDDING_MODEL_DIMENSIONS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
}

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

SimulationEngine = Literal["none", "oasis"]
PersonaGenerator = Literal["deepseek", "stub"]
LLMProvider = Literal["cerebras", "deepseek"]
# Cerebras: low|medium|high. DeepSeek: none|low|high|max (medium/xhigh map on API).
LLMReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]

CEREBRAS_DEFAULT_MODEL = "gpt-oss-120b"
CEREBRAS_DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/opinionssimulator.db"
    allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://localhost:3000",
        "https://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    # Shared OpenAI-compatible chat/completions. No provider fallback.
    llm_provider: LLMProvider = "cerebras"
    # Empty uses the selected provider default (Cerebras gpt-oss-120b / DEEPSEEK_MODEL).
    llm_model: str = ""
    llm_reasoning_effort: LLMReasoningEffort = "medium"
    llm_max_tokens: int = Field(default=8192, ge=1)
    # None = omit sampling param (provider default).
    llm_temperature: float | None = Field(default=None, ge=0, le=2)
    llm_top_p: float | None = Field(default=None, gt=0, le=1)
    llm_timeout_seconds: float = 60.0
    cerebras_api_key: str = ""
    cerebras_base_url: str = CEREBRAS_DEFAULT_BASE_URL
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    # stub = weighted random (tests only); deepseek = call the selected chat LLM
    persona_generator: PersonaGenerator = "deepseek"

    # OpenAI embeddings for SSR and knowledge ingest (separate from chat LLM / CAMEL).
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-large"
    embedding_dimension: int = 3072
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

    # lagen-nu-mcp. Empty URL uses the mock corpus. Set URL to talk live (fail loud).
    lagen_nu_mcp_url: str = ""
    lagen_nu_mcp_key: str = ""
    # Official lagen.nu MCP for the generic research KnowledgeProvider. No auth.
    lagen_nu_official_mcp_url: str = "https://lagen.nu/mcp"
    lagen_nu_official_mcp_timeout_seconds: float = Field(default=20.0, gt=0)

    # Supabase Auth — JWT verify + Admin invite (service_role never goes to the SPA).
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_role_key: str = ""
    # Local-only shortcut: POST /auth/local-login. Never enable in production.
    allow_local_login: bool = False
    # Supabase Storage S3-compatible API (Dashboard → Storage → S3 access keys).
    supabase_s3_access_key_id: str = ""
    supabase_s3_secret_access_key: str = ""
    supabase_s3_region: str = ""
    # LibreOffice binary for Word→PDF underlag conversion (empty = soffice/libreoffice on PATH).
    libreoffice_bin: str = ""

    # none = status-only start; oasis = live CAMEL OASIS spike (optional dep group)
    simulation_engine: SimulationEngine = "none"
    # Cap overlapping run_simulate background jobs (A/B variants within one job
    # still run concurrently; this limits distinct körningar fighting for the API).
    max_concurrent_simulation_jobs: int = Field(default=2, ge=1, le=32)
    # Max concurrent LLM calls when generating personas in one population batch.
    # 1 = serial (debug); higher values overlap profile/anecdote waves.
    persona_generate_concurrency: int = Field(default=8, ge=1, le=32)
    # Max concurrent ResearchNeed executions under one Attempt.
    research_need_concurrency: int = Field(default=8, ge=1, le=32)
    # Follow-up waves after the initial ResearchNeed wave (wave 0).
    research_max_follow_up_waves: int = Field(default=2, ge=0, le=8)
    # Initial + derived ResearchNeeds allowed on one Attempt.
    research_max_needs_per_attempt: int = Field(default=16, ge=1, le=64)
    # Global completeness reviews after local sufficiency. Prevents cycles.
    research_max_completeness_passes: int = Field(default=2, ge=1, le=8)
    # Bounded Question → Evidence graph read-through before provider retrieval.
    research_knowledge_lookup_limit: int = Field(default=10, ge=1, le=32)
    # Age after which reused graph evidence is stale. None = freshness unknown.
    research_knowledge_freshness_max_age_seconds: int | None = Field(
        default=None, ge=1
    )
    # Max concurrent Word-review LLM calls within one expertgranskning job.
    word_review_max_concurrency: int = Field(default=8, ge=1, le=32)
    # Optional Word router override. Empty inherits the global LLM model.
    word_review_router_model: str = ""
    word_review_router_max_tokens: int = Field(default=256, ge=16, le=2048)
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

    @field_validator("llm_model", "word_review_router_model")
    @classmethod
    def strip_optional_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("cerebras_api_key", "deepseek_api_key")
    @classmethod
    def strip_provider_api_key(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_selected_llm_credentials(self) -> Self:
        key = self.selected_llm_api_key
        if not key:
            env_name = self.chat_llm_key_env_name
            raise ValueError(
                f"{env_name} is required when LLM_PROVIDER={self.llm_provider} "
                "— set it in backend/.env (no heuristic/stub LLM fallback)"
            )
        return self

    @model_validator(mode="after")
    def require_embedding_model_matches_dimension(self) -> Self:
        expected = EMBEDDING_MODEL_DIMENSIONS.get(self.embedding_model)
        if expected is not None and self.embedding_dimension != expected:
            raise ValueError(
                f"EMBEDDING_MODEL {self.embedding_model!r} requires "
                f"EMBEDDING_DIMENSION={expected}, got {self.embedding_dimension}"
            )
        if self.embedding_dimension < 1:
            raise ValueError("EMBEDDING_DIMENSION must be >= 1")
        return self

    @field_validator("openai_api_key")
    @classmethod
    def require_openai_api_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError(
                "OPENAI_API_KEY is required — set it in backend/.env "
                "(OpenAI embeddings for SSR; separate from chat LLM)"
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
    def chat_llm_key_env_name(self) -> str:
        if self.llm_provider == "cerebras":
            return "CEREBRAS_API_KEY"
        if self.llm_provider == "deepseek":
            return "DEEPSEEK_API_KEY"
        raise RuntimeError(f"unknown LLM_PROVIDER: {self.llm_provider}")

    @property
    def selected_llm_api_key(self) -> str:
        if self.llm_provider == "cerebras":
            return self.cerebras_api_key
        if self.llm_provider == "deepseek":
            return self.deepseek_api_key
        raise RuntimeError(f"unknown LLM_PROVIDER: {self.llm_provider}")

    @property
    def selected_llm_base_url(self) -> str:
        if self.llm_provider == "cerebras":
            return self.cerebras_base_url
        if self.llm_provider == "deepseek":
            return self.deepseek_base_url
        raise RuntimeError(f"unknown LLM_PROVIDER: {self.llm_provider}")

    @property
    def selected_llm_model(self) -> str:
        override = self.llm_model.strip()
        if override:
            return override
        if self.llm_provider == "cerebras":
            return CEREBRAS_DEFAULT_MODEL
        if self.llm_provider == "deepseek":
            return self.deepseek_model
        raise RuntimeError(f"unknown LLM_PROVIDER: {self.llm_provider}")

    @property
    def selected_reasoning_effort(self) -> LLMReasoningEffort:
        if self.llm_provider in ("cerebras", "deepseek"):
            return self.llm_reasoning_effort
        raise RuntimeError(f"unknown LLM_PROVIDER: {self.llm_provider}")

    @property
    def word_review_router_model_override(self) -> str | None:
        return self.word_review_router_model or None

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
