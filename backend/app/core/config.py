from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Pantry Assist API"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "sqlite:///./pantry.db"

    # Security
    secret_key: str = "dev-secret-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # OpenAI / local LLM (for in-app agent)
    openai_api_key: str | None = None
    openai_base_url: str = "http://127.0.0.1:8080/v1"  # llama.cpp server
    openai_model: str = "ggml-org/GLM-4.7-Flash-GGUF:Q8_0"

    # Agent
    agent_enabled: bool = True
    agent_interval_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
