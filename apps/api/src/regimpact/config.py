"""Environment-backed application settings."""

import secrets
from functools import lru_cache
from urllib.parse import urlparse
from uuid import UUID

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
    clause_classifier_mode: str = "disabled"
    clause_classifier_artifact_dir: str = ""
    auth_mode: str = "legacy"
    jwt_secret: str = ""
    access_token_minutes: int = Field(default=30, ge=5, le=1_440)
    entra_tenant_id: str = ""
    entra_issuer: str = ""
    entra_api_audience: str = ""
    entra_jwks_url: str = ""
    entra_clock_skew_seconds: int = Field(default=120, ge=0, le=300)
    entra_max_token_lifetime_seconds: int = Field(default=5_400, ge=600, le=86_400)
    entra_jwks_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    entra_jwks_cache_seconds: int = Field(default=3_600, ge=60, le=21_600)
    companion_access_enabled: bool = False
    companion_client_id: str = ""
    companion_rate_limit_per_minute: int = Field(default=120, ge=1, le=10_000)
    companion_search_rate_limit_per_minute: int = Field(default=30, ge=1, le=1_000)
    companion_rate_limit_timeout_seconds: float = Field(default=1.0, ge=0.1, le=5.0)
    companion_max_evidence_chars: int = Field(default=50_000, ge=1_000, le=200_000)
    demo_mode: bool = False
    demo_admin_email: str = "admin@northstar.local"
    demo_admin_password: str = ""
    demo_analyst_email: str = "analyst@northstar.local"
    demo_analyst_password: str = ""
    demo_viewer_email: str = "viewer@northstar.local"
    demo_viewer_password: str = ""

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        is_production = self.environment.lower() in {"production", "prod"}
        if self.auth_mode not in {"legacy", "dual", "entra", "legacy_headers"}:
            raise ValueError("auth_mode must be legacy, dual, entra, or legacy_headers")
        if self.object_storage_backend not in {"local", "azure_blob"}:
            raise ValueError("object_storage_backend must be local or azure_blob")
        if self.object_storage_backend == "azure_blob" and not self.azure_storage_account_url:
            raise ValueError("azure_blob storage requires REGIMPACT_AZURE_STORAGE_ACCOUNT_URL")
        if self.clause_classifier_mode not in {"disabled", "transformer"}:
            raise ValueError("clause_classifier_mode must be disabled or transformer")
        if self.clause_classifier_mode == "transformer" and not self.clause_classifier_artifact_dir:
            raise ValueError("transformer classifier requires REGIMPACT_CLAUSE_CLASSIFIER_ARTIFACT_DIR")
        legacy_tokens_enabled = self.auth_mode in {"legacy", "dual"}
        if legacy_tokens_enabled and not self.jwt_secret:
            if is_production:
                raise ValueError("production requires REGIMPACT_JWT_SECRET")
            self.jwt_secret = secrets.token_urlsafe(32)
        if self.auth_mode in {"dual", "entra"}:
            required_entra = {
                "REGIMPACT_ENTRA_TENANT_ID": self.entra_tenant_id,
                "REGIMPACT_ENTRA_ISSUER": self.entra_issuer,
                "REGIMPACT_ENTRA_API_AUDIENCE": self.entra_api_audience,
                "REGIMPACT_ENTRA_JWKS_URL": self.entra_jwks_url,
            }
            missing = [name for name, value in required_entra.items() if not value.strip()]
            if missing:
                raise ValueError(f"{self.auth_mode} authentication requires {', '.join(missing)}")
            try:
                tenant_id = str(UUID(self.entra_tenant_id))
                UUID(self.entra_api_audience)
            except ValueError as exc:
                raise ValueError(
                    "REGIMPACT_ENTRA_TENANT_ID and REGIMPACT_ENTRA_API_AUDIENCE "
                    "must be UUIDs"
                ) from exc
            expected_issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
            if self.entra_issuer != expected_issuer:
                raise ValueError(
                    "REGIMPACT_ENTRA_ISSUER must be the tenant-specific Entra v2 issuer"
                )
            jwks_url = urlparse(self.entra_jwks_url)
            if not jwks_url.hostname or jwks_url.username or jwks_url.password:
                raise ValueError("REGIMPACT_ENTRA_JWKS_URL must be an absolute URL without credentials")
            if jwks_url.scheme not in {"http", "https"}:
                raise ValueError("REGIMPACT_ENTRA_JWKS_URL must use HTTP or HTTPS")
            try:
                jwks_port = jwks_url.port
            except ValueError as exc:
                raise ValueError("REGIMPACT_ENTRA_JWKS_URL contains an invalid port") from exc
            if self.environment.lower() != "test":
                expected_jwks_path = f"/{tenant_id}/discovery/v2.0/keys"
                if (
                    jwks_url.scheme != "https"
                    or jwks_url.hostname.lower() != "login.microsoftonline.com"
                    or jwks_port is not None
                    or jwks_url.path != expected_jwks_path
                    or jwks_url.query
                    or jwks_url.fragment
                ):
                    raise ValueError(
                        "REGIMPACT_ENTRA_JWKS_URL must be the tenant-specific Microsoft "
                        "Entra JWKS endpoint"
                    )
        if self.companion_client_id:
            try:
                companion_client_id = UUID(self.companion_client_id)
            except ValueError as exc:
                raise ValueError("REGIMPACT_COMPANION_CLIENT_ID must be a UUID") from exc
            if self.entra_api_audience and str(companion_client_id) == self.entra_api_audience:
                raise ValueError(
                    "REGIMPACT_COMPANION_CLIENT_ID must differ from the API audience"
                )
        if self.companion_access_enabled:
            if self.auth_mode not in {"dual", "entra"}:
                raise ValueError("companion access requires dual or entra authentication")
            if not self.companion_client_id:
                raise ValueError(
                    "companion access requires REGIMPACT_COMPANION_CLIENT_ID"
                )
        if is_production and self.demo_mode:
            raise ValueError("REGIMPACT_DEMO_MODE must be disabled in production")
        if self.demo_mode and self.auth_mode == "entra":
            raise ValueError("demo mode requires legacy or dual authentication")
        if self.demo_mode and not all(
            (
                self.demo_admin_password,
                self.demo_analyst_password,
                self.demo_viewer_password,
            )
        ):
            raise ValueError("demo mode requires all REGIMPACT_DEMO_*_PASSWORD settings")
        if is_production:
            if self.auth_mode == "legacy_headers":
                raise ValueError("production does not permit legacy_headers authentication")
            if legacy_tokens_enabled and len(self.jwt_secret) < 32:
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
