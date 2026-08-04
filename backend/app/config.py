import os
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    # none = status-only start; oasis = live CAMEL OASIS spike (optional dep group)
    simulation_engine: SimulationEngine = "none"

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

    def uses_llm_generator(self) -> bool:
        return self.persona_generator == "deepseek"

    def apply_oasis_env(self) -> None:
        """Mirror DeepSeek credentials into env vars CAMEL reads directly."""
        os.environ.setdefault("OPENAI_API_KEY", self.deepseek_api_key)
        os.environ.setdefault("OPENAI_COMPATIBLE_API_KEY", self.deepseek_api_key)


settings = Settings()
