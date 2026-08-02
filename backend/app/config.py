import os
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SimulationEngine = Literal["none", "oasis"]


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
    # stub = offline weighted random; deepseek = call DeepSeek when key is set
    persona_generator: str = "deepseek"

    # none = status-only start; oasis = live CAMEL OASIS spike (optional dep group)
    simulation_engine: SimulationEngine = "none"
    oasis_max_agents: int = 5
    oasis_max_ticks: int = 2

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def uses_llm_generator(self) -> bool:
        return self.persona_generator == "deepseek" and bool(self.deepseek_api_key)

    def apply_oasis_env(self) -> None:
        """Mirror DeepSeek credentials into env vars CAMEL reads directly."""
        if not self.deepseek_api_key:
            return
        os.environ.setdefault("OPENAI_API_KEY", self.deepseek_api_key)
        os.environ.setdefault("OPENAI_COMPATIBLE_API_KEY", self.deepseek_api_key)


settings = Settings()
