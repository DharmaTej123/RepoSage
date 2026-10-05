"""Dependency Risk analysis orchestration (tasks 2.4-2.7).

Deterministic pipeline (no LLM):
  parse manifests -> query OSV (batch) -> query PyPI staleness
  -> build DependencyReport -> emit structured Findings with provenance.

Degradation rules (Req 3):
* OSV unreachable -> every queried dep gets ``vuln_status=UNAVAILABLE`` and the
  report flags ``osv_unavailable``; the run continues.
* Unpinned dep -> ``UNPINNED`` (cannot reliably query a specific version).
* Successful query with no vulns -> ``CLEAN`` (distinct from UNAVAILABLE).
* PyPI failure -> ``ReleaseInfo(available=False)``; staleness unknown.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analyzers.dependencies.manifest import parse_manifests
from app.analyzers.dependencies.models import (
    DependencyReport,
    DependencyRisk,
    VulnDataStatus,
)
from app.analyzers.dependencies.osv_client import OSVClient, OSVUnavailableError
from app.analyzers.dependencies.pypi_client import PyPIClient
from app.config import Settings
from app.schemas.finding import (
    Evidence,
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "dependency_risk"

_SEVERITY_ORDER = {
    "critical": FindingSeverity.CRITICAL,
    "high": FindingSeverity.HIGH,
    "medium": FindingSeverity.MEDIUM,
    "low": FindingSeverity.LOW,
}


class DependencyRiskAgent:
    def __init__(
        self,
        settings: Settings,
        osv_client: OSVClient | None = None,
        pypi_client: PyPIClient | None = None,
    ):
        self._settings = settings
        self._osv = osv_client or OSVClient()
        self._pypi = pypi_client or PyPIClient()

    def analyze(self, repo_root: Path, manifest_files: list[str]) -> DependencyReport:
        deps = parse_manifests(repo_root, manifest_files)
        report = DependencyReport(manifest_files=list(manifest_files))
        if not deps:
            report.notes.append("No parseable dependencies found in manifests.")
            return report

        pinned = [(d.name, d.version) for d in deps if d.version]

        # --- OSV batch (task 2.2 / 2.4) ----------------------------------
        osv_results: dict[str, list] = {}
        osv_failed = False
        if pinned:
            try:
                batch = self._osv.query_batch(pinned)
                for (name, _version), vulns in zip(pinned, batch):
                    osv_results[name] = vulns
            except OSVUnavailableError:
                osv_failed = True
                report.osv_unavailable = True
                report.notes.append(
                    "OSV vulnerability data unavailable; vulnerability status "
                    "reported as 'unavailable' for pinned dependencies."
                )

        # --- per-dependency risk ----------------------------------------
        for dep in deps:
            if dep.version is None:
                status = VulnDataStatus.UNPINNED
                vulns = []
            elif osv_failed:
                status = VulnDataStatus.UNAVAILABLE
                vulns = []
            else:
                vulns = osv_results.get(dep.name, [])
                status = (
                    VulnDataStatus.VULNERABLE if vulns else VulnDataStatus.CLEAN
                )

            release = None
            try:
                release = self._pypi.get_release_info(
                    dep.name, self._settings.staleness_months
                )
            except Exception as exc:  # defensive; client already degrades
                logger.debug("PyPI unexpected error for %s: %s", dep.name, exc)

            report.dependencies.append(
                DependencyRisk(
                    dependency=dep,
                    vuln_status=status,
                    vulnerabilities=vulns,
                    release=release,
                )
            )
        return report

    # --- findings (task 2.6) --------------------------------------------
    def to_findings(self, report: DependencyReport) -> list[Finding]:
        findings: list[Finding] = []
        for risk in report.dependencies:
            findings.extend(self._vuln_findings(risk))
            stale = self._staleness_finding(risk)
            if stale:
                findings.append(stale)
        if report.osv_unavailable:
            findings.append(self._osv_unavailable_finding(report))
        return findings

    def _vuln_findings(self, risk: DependencyRisk) -> list[Finding]:
        if risk.vuln_status != VulnDataStatus.VULNERABLE:
            return []
        out: list[Finding] = []
        dep = risk.dependency
        for v in risk.vulnerabilities:
            severity = _SEVERITY_ORDER.get(v.severity or "", FindingSeverity.MEDIUM)
            evidence = [
                Evidence(
                    source_type=EvidenceSourceType.EXTERNAL_API,
                    source=v.reference or f"OSV:{v.id}",
                    excerpt=v.summary,
                    metadata={
                        "osv_id": v.id,
                        "aliases": v.aliases,
                        "fixed_versions": v.fixed_versions,
                        "package": dep.name,
                        "version": dep.version,
                    },
                ),
                Evidence(
                    source_type=EvidenceSourceType.FILE,
                    source=dep.source_manifest,
                    excerpt=dep.raw,
                ),
            ]
            fixed = f" Fixed in: {', '.join(v.fixed_versions)}." if v.fixed_versions else ""
            out.append(
                Finding(
                    agent=AGENT_NAME,
                    category="vulnerable_dependency",
                    title=f"{dep.name} {dep.version} affected by {v.id}",
                    severity=severity,
                    confidence=0.95,
                    description=(v.summary or f"{dep.name} {dep.version} is affected "
                                 f"by {v.id}.") + fixed,
                    affected_components=[dep.name],
                    evidence=evidence,
                    recommendation=(
                        f"Upgrade {dep.name} to a fixed version"
                        + (f" ({', '.join(v.fixed_versions)})" if v.fixed_versions else "")
                        + "."
                    ),
                    deterministic_signals={
                        "kind": dep.kind.value,
                        "vuln_id": v.id,
                        "severity": v.severity,
                    },
                    status=FindingStatus.OBSERVED,
                )
            )
        return out

    def _staleness_finding(self, risk: DependencyRisk) -> Finding | None:
        rel = risk.release
        dep = risk.dependency
        if not rel or not rel.available or not rel.is_stale:
            return None
        return Finding(
            agent=AGENT_NAME,
            category="stale_dependency",
            title=f"{dep.name} appears stale",
            severity=FindingSeverity.LOW,
            confidence=0.7,
            description=(
                f"{dep.name} latest release {rel.latest_version} was published "
                f"on {rel.last_release_date.date() if rel.last_release_date else 'unknown'}, "
                f"older than the {self._settings.staleness_months}-month threshold."
            ),
            affected_components=[dep.name],
            evidence=[
                Evidence(
                    source_type=EvidenceSourceType.EXTERNAL_API,
                    source=f"https://pypi.org/project/{dep.name}/",
                    metadata={
                        "latest_version": rel.latest_version,
                        "last_release_date": (
                            rel.last_release_date.isoformat()
                            if rel.last_release_date else None
                        ),
                    },
                )
            ],
            recommendation=f"Review whether {dep.name} is still maintained.",
            deterministic_signals={"is_stale": True, "kind": dep.kind.value},
            status=FindingStatus.OBSERVED,
        )

    def _osv_unavailable_finding(self, report: DependencyReport) -> Finding:
        return Finding(
            agent=AGENT_NAME,
            category="analysis_gap",
            title="Vulnerability data unavailable",
            severity=FindingSeverity.INFO,
            confidence=1.0,
            description=(
                "OSV vulnerability data could not be retrieved; vulnerability "
                "status for pinned dependencies is unknown for this run."
            ),
            affected_components=[],
            status=FindingStatus.OBSERVED,
        )

    def close(self) -> None:
        self._osv.close()
        self._pypi.close()
