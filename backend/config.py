"""Application configuration via pydantic-settings.

One Settings class, one instance, cached. Reads from environment
and .env file.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = Field(
        ...,
        description="postgresql+asyncpg://user:pass@host:port/db",
    )

    # Auth — JWT for local accounts
    jwt_secret_key: str = Field(
        ..., min_length=32,
        description="HS256 secret. Generate with secrets.token_hex(32).",
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 8  # 8 hours

    # Auth — Google OAuth (optional; if unset, only local auth works)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # VLM provider
    vlm_provider: str = Field(
        "openai",
        description="One of: 'openai', 'anthropic', 'vllm_local'",
    )
    vlm_endpoint: str = Field("https://api.openai.com/v1")
    vlm_api_key: str | None = None
    vlm_model: str = Field("gpt-4o-mini")

    # Service info
    service_name: str = "dermassist-vn"
    log_level: str = "INFO"
    base_url: str = Field(
        "http://localhost:8000",
        description="Base URL for the deployed app, used in OAuth redirect.",
    )

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
