"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets and credentials come from the environment."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Allow MODEL_* env fields without colliding with Pydantic's model_ namespace.
        protected_namespaces=(),
    )

    app_name: str = "AI Operations Assistant"
    app_env: str = "development"
    debug: bool = True

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    database_url: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_operations_assistant"
    )

    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60

    model_provider: str = ""
    model_name: str = ""
    model_api_key: str = ""

    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return value
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
