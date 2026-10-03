"""Application settings loaded from environment variables."""

import ast
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend service."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        protected_namespaces=(),
    )

    app_name: str = "AI Operations Assistant"
    app_env: str = "development"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/ai_operations"
    jwt_secret: str = "change_this_in_development"
    jwt_expire_minutes: int = 60
    seed_admin_password: str = ""
    seed_ops_password: str = ""
    seed_manager_password: str = ""
    seed_viewer_password: str = ""

    model_provider: str = ""
    model_name: str = ""
    model_api_key: str = ""

    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str, info: Any) -> str:
        if info.data.get("app_env", "development") not in {"development", "test"}:
            if not value or value == "change_this_in_development":
                raise ValueError("JWT_SECRET must be set to a secure value outside development.")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = ast.literal_eval(raw)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except (ValueError, SyntaxError):
                    pass
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value


def get_settings() -> Settings:
    """Return settings from the current environment without freezing stale values."""
    return Settings()


def _clear_settings_cache() -> None:
    """Compatibility shim for tests that call get_settings.cache_clear()."""
    return None


get_settings.cache_clear = _clear_settings_cache
