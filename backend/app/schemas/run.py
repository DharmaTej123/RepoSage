"""API request/response schemas for run ingestion and status."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class SubmitRunRequest(BaseModel):
    """Submit a repository for analysis (Req 1, 12).

    Exactly one of ``repo_url`` / ``repo_path`` must be provided.
    """

    repo_url: str | None = Field(default=None, description="Git URL to clone.")
    repo_path: str | None = Field(
        default=None, description="Local filesystem path to copy."
    )
    objective: str | None = Field(
        default=None,
        description="Optional user objective to guide the investigation plan.",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "SubmitRunRequest":
        if bool(self.repo_url) == bool(self.repo_path):
            raise ValueError("Provide exactly one of repo_url or repo_path.")
        return self


class SubmitRunResponse(BaseModel):
    """202-style acknowledgement returned immediately after submission."""

    job_id: str
    run_id: str
    repo_id: str
    status: JobStatus


class RepositoryMetadata(BaseModel):
    """Immutable per-run repository facts recorded at ingestion (Req 1)."""

    revision: str = Field(..., description="Analyzed HEAD commit sha.")
    size_mb: float
    language: str
    manifest_files: list[str] = Field(default_factory=list)
    ingested_at: datetime


class RunStatusResponse(BaseModel):
    job_id: str
    run_id: str
    repo_id: str
    status: JobStatus
    revision: str | None = None
    error: str | None = None
    repository: RepositoryMetadata | None = None
    agent_status: dict[str, str] = Field(default_factory=dict)
