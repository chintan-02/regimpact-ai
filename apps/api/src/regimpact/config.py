"""Environment-backed application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REGIMPACT_", env_file=".env", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://regimpact:regimpact@localhost:5432/regimpact"
    )
    object_storage_root: str = "/tmp/regimpact-objects"
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_pdf_pages: int = Field(default=500, ge=1, le=2_000)
    malware_scanner_mode: str = "development_allow"
    redis_url: str = "redis://localhost:6379/0"
    worker_time_limit_ms: int = Field(default=120_000, ge=1_000, le=900_000)
    source_allowed_domains: str = ""
    source_request_timeout_seconds: float = Field(default=20.0, ge=1.0, le=60.0)
    embedding_provider: str = "feature_hash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

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
