"""Data models for dependency-risk analysis (Phase 2).

Key distinctions the spec insists on (Req 3):
* direct vs transitive dependencies,
* "no vulnerability found" vs "vulnerability data unavailable",
* external-source provenance on vulnerability / release findings.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DependencyKind(str, Enum):
    DIRECT = "direct"
    TRANSITIVE = "transitive"


class VulnDataStatus(str, Enum):
    """Whether we actually obtained vulnerability data for a dependency."""

    CLEAN = "clean"              # queried successfully, no vulns
    VULNERABLE = "vulnerable"    # queried successfully, vulns found
    UNAVAILABLE = "unavailable"  # could not query (network/API error)
    UNPINNED = "unpinned"        # no concrete version -> cannot query reliably


class Dependency(BaseModel):
    name: str
    version: str | None = None          # None when unpinned / range-only
    raw: str                            # the original manifest specifier line
    kind: DependencyKind = DependencyKind.DIRECT
    source_manifest: str                # e.g. "requirements.txt"


class Vulnerability(BaseModel):
    id: str                              # e.g. "GHSA-xxxx" / "CVE-xxxx"
    summary: str | None = None
    severity: str | None = None          # normalized: critical/high/medium/low
    aliases: list[str] = Field(default_factory=list)
    fixed_versions: list[str] = Field(default_factory=list)
    reference: str | None = None         # OSV/GHSA url


class ReleaseInfo(BaseModel):
    latest_version: str | None = None
    last_release_date: datetime | None = None
    is_stale: bool = False
    available: bool = True               # False if PyPI lookup failed


class DependencyRisk(BaseModel):
    dependency: Dependency
    vuln_status: VulnDataStatus
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    release: ReleaseInfo | None = None


class DependencyReport(BaseModel):
    manifest_files: list[str] = Field(default_factory=list)
    dependencies: list[DependencyRisk] = Field(default_factory=list)
    # True when the OSV service was unreachable for any batch (Req 3 / 2.4).
    osv_unavailable: bool = False
    notes: list[str] = Field(default_factory=list)
