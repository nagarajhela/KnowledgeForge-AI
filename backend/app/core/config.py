from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    APP_NAME: str = "KnowledgeForge AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    # Security & Crypto
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production-at-least-32-bytes",
        min_length=16,
    )
    ENCRYPTION_KEY: str = "dev-encryption-passphrase-for-provider-api-keys"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    COOKIE_AUTH_ENABLED: bool = False

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://knowledgeforge:knowledgeforge@localhost:5432/knowledgeforge"
    )
    DATABASE_SYNC_URL: str = (
        "postgresql+psycopg://knowledgeforge:knowledgeforge@localhost:5432/knowledgeforge"
    )
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    ENABLE_POSTGRES_RLS: bool = False

    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Storage
    STORAGE_BACKEND: Literal["s3", "local"] = "s3"
    LOCAL_STORAGE_PATH: str = "/tmp/knowledgeforge-storage"
    S3_ENDPOINT_URL: str | None = "http://localhost:9000"
    S3_PUBLIC_ENDPOINT_URL: str | None = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "knowledgeforge-documents"
    S3_REGION: str = "us-east-1"
    MAX_UPLOAD_SIZE_MB: int = 50

    # AI / RAG Providers
    DEFAULT_LLM_PROVIDER: Literal["openai", "azure_openai", "anthropic", "ollama", "mock"] = "mock"
    DEFAULT_LLM_MODEL: str = "gpt-4o-mini"
    DEFAULT_EMBEDDING_PROVIDER: Literal["openai", "azure_openai", "ollama", "mock"] = "mock"
    DEFAULT_EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    AZURE_OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_API_VERSION: str = "2024-08-01-preview"
    ANTHROPIC_API_KEY: str | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # CORS & Frontend
    FRONTEND_URL: str = "http://localhost:3001"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000"

    # OAuth2
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    MICROSOFT_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/microsoft/callback"

    # Billing
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_STARTER: str = "price_starter_monthly"
    STRIPE_PRICE_PRO: str = "price_pro_monthly"
    STRIPE_PRICE_ENTERPRISE: str = "price_enterprise_monthly"

    # Malware Scanning
    VIRUS_SCANNER_BACKEND: Literal["noop", "clamav"] = "noop"
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
