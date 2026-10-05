"""Application configuration.

All tunable limits referenced across the specification live here so they can be
driven by environment variables / a `.env` file rather than being hardcoded at
call sites (Req 15: configurable repo size, history window, sandbox runtime,
thresholds, LLM budget).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from environment / .env.

    Environment variables are prefixed with ``REPOSAGE_`` (e.g.
    ``REPOSAGE_MAX_REPO_SIZE_MB=1024``).
    """

    model_config = SettingsConfigDict(
        env_prefix="REPOSAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---------------------------------------------------------
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # --- Storage / working directories -----------------------------------
    # Root directory holding immutable per-run repository snapshots.
    workdir_root: Path = Field(default=Path("./.reposage/workdir"))

    # --- Datastores (later phases connect to these) ----------------------
    database_url: str = Field(
        default="postgresql+psycopg://reposage:reposage@localhost:5432/reposage",
        description="SQLAlchemy URL for the Postgres system-of-record.",
    )
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="reposage")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Ingestion limits (Req 1) ----------------------------------------
    max_repo_size_mb: float = Field(
        default=1024,
        description="Reject repositories larger than this after ingestion.",
        gt=0,
    )
    clone_depth: int | None = Field(
        default=None,
        description="Optional shallow-clone depth. None = full history (needed "
        "for git-history analysis).",
    )

    # --- Git history window (Req 4) --------------------------------------
    history_window_days: int = Field(
        default=730,  # ~2 years
        description="Cap git-history mining to this recent window.",
        ge=1,
    )
    recent_activity_days: int = Field(
        default=365,  # 12 months
        description="Window used for 'recent' commit-count / ownership metrics.",
        ge=1,
    )

    # --- Thresholds ------------------------------------------------------
    bus_factor_threshold: float = Field(
        default=0.80,
        description="Single-author share above which a module is bus-factor risk.",
        ge=0.0,
        le=1.0,
    )
    coverage_gap_threshold: float = Field(
        default=0.50,
        description="Coverage fraction below which a central module is a gap.",
        ge=0.0,
        le=1.0,
    )
    staleness_months: int = Field(
        default=18,
        description="Dependency considered stale if last release older than this.",
        ge=1,
    )

    # --- Sandbox limits (Req 6) ------------------------------------------
    sandbox_cpu_limit: float = Field(default=2.0, gt=0)
    sandbox_memory_mb: int = Field(default=2048, ge=64)
    sandbox_timeout_seconds: int = Field(default=600, ge=1)
    sandbox_pids_limit: int = Field(default=256, ge=1)

    # --- LLM budget / observability (Req 15) -----------------------------
    llm_max_tokens_per_run: int = Field(default=200_000, ge=0)
    langsmith_tracing: bool = Field(default=False)
    langsmith_project: str = Field(default="reposage")

    def resolved_workdir_root(self) -> Path:
        """Absolute, created-on-demand working-directory root."""
        root = self.workdir_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (safe to call from anywhere / DI)."""
    return Settings()
