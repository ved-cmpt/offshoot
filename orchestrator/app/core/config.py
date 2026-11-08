"""Application settings, read from the environment. Secrets are never logged."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PLACEHOLDER_MARKERS = ("change-me", "changeme", "placeholder")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    demo_mode: bool = True
    ai_mode: Literal["mock", "gemini"] = "mock"

    database_url: SecretStr
    migration_database_url: SecretStr | None = None

    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "parityforge"
    jwt_audience: str = "parityforge-api"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=604800, ge=3600)

    cookie_secure: bool = True
    cors_origins: Annotated[list[str], NoDecode] = []
    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    login_rate_limit_ip_per_minute: int = Field(default=60, ge=1)

    demo_password_viewer: SecretStr = SecretStr("")
    demo_password_engineer: SecretStr = SecretStr("")
    demo_password_architect: SecretStr = SecretStr("")
    demo_password_admin: SecretStr = SecretStr("")

    billrite_path: str = "/legacy/billrite"

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    ai_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ai_project_call_budget: int = Field(default=50, ge=0)
    ai_low_confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    # Blueprint Section 3.4: the demo allows approving your own edit, with an audit flag.
    allow_self_approval: bool = True

    job_worker_enabled: bool = True
    job_poll_seconds: float = Field(default=0.5, gt=0)
    job_lease_seconds: int = Field(default=300, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def refuse_placeholders_in_production(self) -> "Settings":
        if self.app_env == "production":
            secret = self.jwt_secret.get_secret_value().lower()
            if any(marker in secret for marker in PLACEHOLDER_MARKERS):
                raise ValueError("JWT_SECRET still holds a placeholder value")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
