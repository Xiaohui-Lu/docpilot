"""Application settings, loaded from environment variables (12-factor style)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOCPILOT_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./docpilot.db"
    jwt_secret: str = "dev-only-insecure-jwt-secret-change-me"
    jwt_ttl_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173"
    upload_max_mb: int = 15

    # LLM provider: "demo" runs fully offline with deterministic heuristics (no API key, no cost);
    # "claude" calls the Anthropic API.
    llm_provider: Literal["demo", "claude"] = "demo"
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_refusal_fallback: bool = True
    llm_timeout_seconds: float = 120.0

    # Create tables on startup (dev convenience). In docker-compose / Kubernetes a one-shot
    # migrate step owns the schema instead, so replicas never race each other.
    auto_create_schema: bool = True

    # Background jobs
    worker_embedded: bool = True  # run a worker thread inside the API process (handy for local dev)
    worker_poll_seconds: float = 1.0
    job_max_attempts: int = 4
    job_lock_timeout_seconds: int = 600

    # Alerts / email. With no SMTP host, emails are written to `outbox_dir` as .eml files (dev default).
    app_base_url: str = "http://localhost:5173"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_from: str = "DocPilot <alerts@docpilot.example.com>"
    outbox_dir: str = "./outbox"
    digest_check_seconds: int = 600

    # Retrieval
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    retrieval_top_k: int = 6

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
