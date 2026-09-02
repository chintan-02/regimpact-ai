"""Environment-backed application settings."""

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REGIMPACT_", env_file=".env", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    metrics_enabled: bool = True
    database_url: str = Field(
        default="postgresql+psycopg://regimpact:regimpact@localhost:5432/regimpact"
    )
    object_storage_root: str = "/tmp/regimpact-objects"
    object_storage_backend: str = "local"
    azure_storage_account_url: str = ""
    azure_storage_container: str = "documents"
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_pdf_pages: int = Field(default=500, ge=1, le=2_000)
    malware_scanner_mode: str = "development_allow"
    redis_url: str = "redis://localhost:6379/0"
    worker_time_limit_ms: int = Field(default=120_000, ge=1_000, le=900_000)
    ingestion_max_attempts: int = Field(default=5, ge=1, le=20)
    ingestion_lease_seconds: int = Field(default=300, ge=30, le=3_600)
    ingestion_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    ingestion_retry_cap_seconds: int = Field(default=300, ge=5, le=3_600)
    source_allowed_domains: str = ""
    source_request_timeout_seconds: float = Field(default=20.0, ge=1.0, le=60.0)
    embedding_provider: str = "feature_hash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    auth_mode: str = "jwt"
    jwt_secret: str = "local-development-secret-change-before-production"
    access_token_minutes: int = Field(default=30, ge=5, le=1_440)
    demo_admin_email: str = "admin@northstar.local"
    demo_admin_password: str = "ChangeMe-Admin-2026!"
    demo_analyst_email: str = "analyst@northstar.local"
    demo_analyst_password: str = "ChangeMe-Analyst-2026!"
    demo_viewer_email: str = "viewer@northstar.local"
    demo_viewer_password: str = "ChangeMe-Viewer-2026!"

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.auth_mode not in {"jwt", "legacy_headers"}:
            raise ValueError("auth_mode must be jwt or legacy_headers")
        if self.object_storage_backend not in {"local", "azure_blob"}:
            raise ValueError("object_storage_backend must be local or azure_blob")
        if self.object_storage_backend == "azure_blob" and not self.azure_storage_account_url:
            raise ValueError("azure_blob storage requires REGIMPACT_AZURE_STORAGE_ACCOUNT_URL")
        if self.environment.lower() in {"production", "prod"}:
            if self.auth_mode != "jwt":
                raise ValueError("production requires JWT authentication")
            if self.jwt_secret == "local-development-secret-change-before-production":
                raise ValueError("production requires a unique REGIMPACT_JWT_SECRET")
            if len(self.jwt_secret) < 32:
                raise ValueError("REGIMPACT_JWT_SECRET must contain at least 32 characters")
        return self

    @property
    def allowed_source_domains(self) -> frozenset[str]:
        return frozenset(
            value.strip().lower()
            for value in self.source_allowed_domains.split(",")
            if value.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
