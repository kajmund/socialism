import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.database_url import normalize_database_url

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

    database_url: str

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> str:
        return normalize_database_url(value)

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
    # TypeSafe Jev classifies Auto task needs. Empty key disables Auto classification.
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    jev_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    jev_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    jev_state_char_budget: int = Field(default=8000, ge=256, le=32_000)
    # Document-understanding batches are bounded separately from the global LLM
    # settings. They contain at most 20 short items and should never inherit a
    # very large global completion budget.
    document_knowledge_llm_max_tokens: int = Field(default=8192, ge=512, le=32768)
    document_knowledge_llm_timeout_seconds: float = Field(default=180.0, gt=0, le=900)
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
    google_live_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_live_model: str = "gemini-2.5-flash-native-audio-latest"
    gemini_live_voice: str = "Algenib"
    gemini_live_token_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    gemini_live_new_session_ttl_seconds: int = Field(default=60, ge=30, le=300)
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com"
    # Write-through cache for SSR anchor embeddings (memory + disk).
    embedding_cache_dir: str = "data/embedding_cache"
    # Budskap image bytes + vision captions keyed by SHA256.
    image_cache_dir: str = "data/image_cache"
    # Persistent expert memory in the configured Supabase Postgres database.
    mem0_collection_name: str = "expert_memories"
    mem0_embedding_model: str = "text-embedding-3-small"
    mem0_search_limit: int = Field(default=10, ge=1, le=50)
    mem0_vision_model: str = "qwen-3.8-27b"
    mem0_vision_details: Literal["auto", "low", "high"] = "high"
    mem0_telemetry: bool = False
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
    lagen_nu_official_mcp_timeout_seconds: float = Field(default=60.0, gt=0)

    # Supabase Auth — JWKS verify + Admin invite (service_role never goes to the SPA).
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    # Storage Vector Bucket used by the research provider in the product project.
    supabase_vector_bucket: str = "research-knowledge"
    supabase_vector_index: str = "documents-openai"
    supabase_vector_distance_metric: Literal["cosine", "euclidean"] = "cosine"
    # Local-only shortcut: POST /auth/local-login. Never enable in production.
    allow_local_login: bool = False
    local_auth_jwt_secret: str = ""
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
    # Jev is a research control primitive, not chat-LLM routing.
    research_jev_enabled: bool = False
    research_jev_mode: Literal["shadow", "active"] = "shadow"
    research_jev_model: str = "jev-1.12"
    research_jev_sufficient_threshold: float = Field(default=0.9, ge=0.5, le=1.0)
    research_jev_incomplete_threshold: float = Field(default=0.85, ge=0.5, le=1.0)
    research_jev_confidence_threshold: float = Field(default=0.8, ge=0.5, le=1.0)
    research_jev_max_evidence_items: int = Field(default=24, ge=1, le=100)
    research_jev_max_state_chars: int = Field(default=6000, ge=256, le=32_000)
    research_jev_concurrency: int = Field(default=8, ge=1, le=32)
    research_jev_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    research_jev_evidence_screen_enabled: bool = True
    # Bounded Question → Evidence graph read-through before provider retrieval.
    research_knowledge_lookup_limit: int = Field(default=10, ge=1, le=32)
    research_question_semantic_match_threshold: float = Field(
        default=0.88, ge=0.0, le=1.0
    )
    research_question_semantic_match_limit: int = Field(default=8, ge=1, le=32)
    research_question_embedding_version: str = Field(
        default="knowledge-question-v1", min_length=1
    )
    # Age after which reused graph evidence is stale. None = freshness unknown.
    research_knowledge_freshness_max_age_seconds: int | None = Field(
        default=None, ge=1
    )
    # Background research lease. Expired claims are reclaimable by another worker.
    research_claim_lease_seconds: int = Field(default=60, ge=5, le=3600)
    # How often the reclaim loop looks for expired/unclaimed research work.
    research_worker_poll_seconds: float = Field(default=0.5, ge=0.05, le=60)
    # Normal app startup starts a reclaim loop in lifespan. Tests turn this off.
    research_worker_loop_enabled: bool = True
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
    # Optional authenticated HTTPS log drain. Records are queued off the request path.
    logstash_url: str = ""
    logstash_username: str = ""
    logstash_password: SecretStr = SecretStr("")
    log_service: str = "socialism-backend"
    log_environment: str = "local"
    logstash_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    logstash_queue_size: int = Field(default=512, ge=1, le=10_000)

    @field_validator("log_level")
    @classmethod
    def require_log_level(cls, value: str) -> str:
        name = value.strip().upper()
        if name not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return name

    @model_validator(mode="after")
    def require_complete_logstash_config(self) -> Self:
        url = self.logstash_url.strip()
        username = self.logstash_username.strip()
        password = self.logstash_password.get_secret_value()
        configured = (bool(url), bool(username), bool(password))
        if any(configured) and not all(configured):
            raise ValueError(
                "LOGSTASH_URL, LOGSTASH_USERNAME, and LOGSTASH_PASSWORD must be set together"
            )
        if url and not url.startswith("https://"):
            raise ValueError("LOGSTASH_URL must use HTTPS")
        if not self.log_service.strip():
            raise ValueError("LOG_SERVICE must not be empty")
        if not self.log_environment.strip():
            raise ValueError("LOG_ENVIRONMENT must not be empty")
        return self

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

    @field_validator(
        "mem0_collection_name",
        "mem0_embedding_model",
        "mem0_vision_model",
    )
    @classmethod
    def require_mem0_value(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Mem0 settings must not be empty")
        return cleaned

    @field_validator("mem0_vision_model")
    @classmethod
    def require_non_gpt_mem0_vision_model(cls, value: str) -> str:
        if "gpt" in value.casefold():
            raise ValueError("MEM0_VISION_MODEL must be a Cerebras vision model, not GPT/gpt-oss")
        return value

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
    def require_mem0_vision_credentials(self) -> Self:
        if not self.cerebras_api_key:
            raise ValueError(
                "CEREBRAS_API_KEY is required for Mem0 multimodal expert memory"
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

    @field_validator("supabase_vector_bucket", "supabase_vector_index")
    @classmethod
    def require_supabase_vector_names(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Supabase vector bucket and index names must not be empty")
        return name

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
# Mem0 reads this directly during import. Mirror the typed setting here so the
# SDK never owns application configuration or enables outbound telemetry.
os.environ["MEM0_TELEMETRY"] = "true" if settings.mem0_telemetry else "false"
