"""Test Coverage Gap Agent (tasks 5.4, 5.5, 5.6).

Executes the repo test suite inside the sandbox, then cross-references the
resulting per-module coverage against architecture centrality (from the run
state) to flag high-centrality / low-coverage modules as risk areas (Req 5).

Coverage is NEVER computed by an LLM and repo code is only executed via the
sandbox runner (Req 6). When no test runner exists or the sandbox is
unavailable, the agent returns a skip-with-reason result rather than pretending
coverage is clean.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analyzers.graph import ModuleGraph
from app.analyzers.models import ArchitectureGraph
from app.config import Settings
from app.sandbox.models import SandboxResult, SandboxStatus
from app.sandbox.runner import SandboxRunner, get_sandbox_runner
from app.schemas.finding import (
    Evidence,
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "coverage"


class CoverageGapAgent:
    def __init__(self, settings: Settings, runner: SandboxRunner | None = None):
        self._settings = settings
        self._runner = runner or get_sandbox_runner(settings)

    def run(self, repo_root: Path) -> SandboxResult:
        return self._runner.run_coverage(Path(repo_root))

    def to_findings(
        self, result: SandboxResult, architecture: ArchitectureGraph | None
    ) -> list[Finding]:
        # No coverage data -> no coverage-gap findings (do not fabricate).
        if not result.coverage_available or architecture is None:
            return []

        graph = ModuleGraph.from_architecture(architecture)
        threshold = self._settings.coverage_gap_threshold
        candidates = graph.high_centrality_low_coverage(
            architecture.centrality, result.coverage_by_file, threshold
        )

        findings: list[Finding] = []
        for centrality, cov in candidates:
            # Only emit when coverage is KNOWN and below threshold.
            if cov is None:
                continue
            module = centrality.module
            node = next((n for n in architecture.nodes if n.id == module), None)
            severity = (
                FindingSeverity.HIGH if centrality.in_degree >= 3 and cov < threshold / 2
                else FindingSeverity.MEDIUM
            )
            findings.append(
                Finding(
                    agent=AGENT_NAME,
                    category="coverage_gap",
                    title=f"High-centrality module with low coverage: {module}",
                    severity=severity,
                    confidence=0.85,
                    description=(
                        f"Module '{module}' has PageRank {centrality.pagerank:.4f} "
                        f"(in-degree {centrality.in_degree}) but only "
                        f"{cov:.0%} line coverage, below the "
                        f"{threshold:.0%} threshold. Central, under-tested code "
                        f"is a change-risk hotspot."
                    ),
                    affected_components=[module],
                    evidence=[
                        Evidence(
                            source_type=EvidenceSourceType.COMMAND,
                            source="pytest --cov (sandbox)",
                            location=(node.file_path if node else None),
                            metadata={
                                "coverage": cov,
                                "pagerank": centrality.pagerank,
                                "in_degree": centrality.in_degree,
                            },
                        ),
                        Evidence(
                            source_type=EvidenceSourceType.GRAPH,
                            source=f"module:{module}",
                            metadata={"in_degree": centrality.in_degree},
                        ),
                    ],
                    recommendation=(
                        f"Add tests for '{module}' before making changes; "
                        f"prioritize by its high dependency centrality."
                    ),
                    deterministic_signals={
                        "coverage": cov,
                        "pagerank": centrality.pagerank,
                        "in_degree": centrality.in_degree,
                        "threshold": threshold,
                    },
                    status=FindingStatus.OBSERVED,
                )
            )
        return findings

    @staticmethod
    def skip_reason(result: SandboxResult) -> str | None:
        if result.status == SandboxStatus.NO_RUNNER:
            return result.error or "no discoverable test runner"
        if result.status == SandboxStatus.UNAVAILABLE:
            return result.error or "sandbox unavailable"
        return None