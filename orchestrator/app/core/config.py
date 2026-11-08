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
    jwt_issuer: str = "offshoot"
    jwt_audience: str = "offshoot-api"
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
    # How the response schema reaches Gemini: as a structured schema, or written into the
    # instructions (ADR-046). The strict contract is validated locally in both modes.
    gemini_schema_mode: Literal["json_schema", "prompt"] = "prompt"
    ai_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ai_project_call_budget: int = Field(default=50, ge=0)
    # A hard cap on live model calls across the whole database, every project together (ADR-046).
    ai_live_call_cap: int = Field(default=30, ge=0)
    ai_low_confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    # Blueprint Section 3.4: the demo allows approving your own edit, with an audit flag.
    allow_self_approval: bool = True

    job_worker_enabled: bool = True
    job_poll_seconds: float = Field(default=0.5, gt=0)
    # A verification with mutation testing can run for many minutes (ADR-023).
    job_lease_seconds: int = Field(default=1800, ge=1)

    # Sandbox runners (ADR-013, ADR-030). Every call carries the shared token.
    cobol_runner_url: str = "http://cobol-runner:9000"
    dotnet_builder_socket: str = "/run/builder/builder.sock"
    runner_shared_secret: SecretStr = SecretStr("")
    runner_timeout_seconds: float = Field(default=1200.0, gt=0)
    # Lower the builder's own limits for this deployment. Unset means the builder's defaults.
    sandbox_test_timeout_seconds: int | None = Field(default=None, ge=1)
    sandbox_run_timeout_seconds: int | None = Field(default=None, ge=1)

    # Migration and verification (Blueprint Sections 6.1, 7.1 and 7.2).
    repair_max_attempts: int = Field(default=3, ge=0, le=3)
    equivalence_cases: int = Field(default=500, ge=20, le=5000)
    equivalence_seed: int = Field(default=20261107, ge=0)
    coverage_threshold: float = Field(default=85.0, ge=0, le=100)
    mutation_threshold: float = Field(default=70.0, ge=0, le=100)
    report_mismatch_limit: int = Field(default=25, ge=1, le=200)

    # Strangler facade (Blueprint Sections 7.3 and 9, ADR-039).
    facade_url: str = "http://facade:8080"
    facade_shared_secret: SecretStr = SecretStr("")
    facade_project: str = "BillRite"
    shadow_sample_size: int = Field(default=20, ge=1, le=10000)

    # Uploads (F03, Blueprint Section 11). Never executed; disabled in demo mode.
    upload_max_bytes: int = Field(default=1024 * 1024, ge=1024)
    upload_max_files: int = Field(default=40, ge=1)
    upload_max_file_bytes: int = Field(default=256 * 1024, ge=1024)
    upload_max_total_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)

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
