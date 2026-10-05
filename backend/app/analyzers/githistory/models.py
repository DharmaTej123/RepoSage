"""Data models for git-history / ownership analysis (Phase 3).

Terminology discipline (Req 4): we speak of *historical contribution* and
*primary contributor*, never *owner*. Historical contribution is a signal, not
a statement of formal code ownership.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CommitRecord(BaseModel):
    sha: str
    author_name: str
    author_email: str
    authored_at: datetime
    changed_files: list[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions


class AuthorContribution(BaseModel):
    """A single author's historical contribution to a module."""

    author_name: str
    author_email: str
    commits: int = 0
    churn: int = 0  # insertions + deletions attributed to this author's touches


class ModuleOwnership(BaseModel):
    module: str
    total_commits: int = 0
    total_churn: int = 0
    # Sorted desc by commits. "primary_contributor" != "owner" (Req 4).
    contributors: list[AuthorContribution] = Field(default_factory=list)
    primary_contributor: str | None = None
    primary_contributor_share: float = 0.0  # fraction of commits by top author
    bus_factor_flag: bool = False

    def as_signals(self) -> dict:
        return {
            "total_commits": self.total_commits,
            "total_churn": self.total_churn,
            "primary_contributor_share": round(self.primary_contributor_share, 4),
            "distinct_contributors": len(self.contributors),
            "bus_factor_flag": self.bus_factor_flag,
        }


class OwnershipReport(BaseModel):
    revision: str
    window_days: int
    commits_analyzed: int = 0
    modules: list[ModuleOwnership] = Field(default_factory=list)
    # True if history was empty / shallow so results are limited.
    limited: bool = False
    notes: list[str] = Field(default_factory=list)
