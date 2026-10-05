"""Sandbox result models (task 5.6)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SandboxStatus(str, Enum):
    COMPLETED = "completed"      # ran to completion (tests may pass or fail)
    TIMEOUT = "timeout"          # wall-clock limit hit, container killed
    NO_RUNNER = "no_runner"      # no test runner discoverable
    ERROR = "error"             # infrastructure error (image/container)
    UNAVAILABLE = "unavailable"  # sandbox backend not available


class SandboxResult(BaseModel):
    status: SandboxStatus
    exit_code: int | None = None
    duration_seconds: float | None = None
    stdout: str = ""
    stderr: str = ""
    # Parsed coverage: per-file line coverage fraction (0..1) when available.
    coverage_available: bool = False
    coverage_by_file: dict[str, float] = Field(default_factory=dict)
    total_coverage: float | None = None
    error: str | None = None
    backend: str = "unknown"  # "docker" | "local" | "none"