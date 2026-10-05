"""Graph node implementations (tasks 4.2-4.9, 4.11).

Each specialist node:
* checks the manager plan and short-circuits to SKIPPED/NOT_APPLICABLE,
* otherwise runs its deterministic analyzer,
* returns findings + analyzer output + a metric via ``run_node``.

Specialists are wrapped so a failure records FAILED and preserves the rest of
the run's partial state (task 4.11).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analyzers.architecture_mapper import ArchitectureMapper
from app.analyzers.dependencies.agent import DependencyRiskAgent
from app.analyzers.githistory.agent import GitHistoryAgent
from app.config import Settings
from app.orchestration.manager import plan_investigation
from app.orchestration.node_utils import NodeResult, run_node
from app.orchestration.state import NodeStatus, RunState
from app.schemas.finding import (
    Evidence,
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)

logger = logging.getLogger(__name__)


# ------------------------- ingest / manager -----------------------------

def manager_node(state: RunState) -> dict:
    plan = plan_investigation(state)
    return {"plan": plan, "node_status": {"manager": NodeStatus.COMPLETE.value}}


def _is_enabled(state: RunState, name: str) -> bool:
    return name in (state.get("plan", {}).get("enabled") or [])


def _skip_reason(state: RunState, name: str) -> str:
    return (state.get("plan", {}).get("skipped") or {}).get(name, "not enabled")


# ------------------------- architecture ----------------------------------

def architecture_node(state: RunState, settings: Settings) -> dict:
    agent = "architecture"

    def body() -> NodeResult:
        if not _is_enabled(state, agent):
            return NodeResult(NodeStatus.SKIPPED, reason=_skip_reason(state, agent))
        mapper = ArchitectureMapper(Path(state["workdir"]), state["revision"])
        arch = mapper.run()
        findings = _architecture_findings(arch)
        status = NodeStatus.COMPLETE if findings else NodeStatus.NO_FINDING
        return NodeResult(
            status,
            update={"architecture": arch, "findings": findings},
            tool_calls=1,
        )

    return run_node(agent, body)


def _architecture_findings(arch) -> list[Finding]:
    """Emit high-centrality module findings (interpretation happens later)."""
    from app.analyzers.graph import ModuleGraph

    g = ModuleGraph.from_architecture(arch)
    top = g.high_centrality_modules(arch.centrality, top_n=5)
    findings: list[Finding] = []
    for c in top:
        if c.in_degree == 0 and c.pagerank == 0:
            continue
        node = next((n for n in arch.nodes if n.id == c.module), None)
        findings.append(
            Finding(
                agent="architecture",
                category="high_centrality",
                title=f"High-centrality module: {c.module}",
                severity=FindingSeverity.INFO,
                confidence=0.9,
                description=(
                    f"Module '{c.module}' has in-degree {c.in_degree} and "
                    f"PageRank {c.pagerank:.4f}, indicating many parts of the "
                    f"codebase depend on it."
                ),
                affected_components=[c.module],
                evidence=[
                    Evidence(
                        source_type=EvidenceSourceType.GRAPH,
                        source=f"module:{c.module}",
                        location=(node.file_path if node else None),
                        metadata={"in_degree": c.in_degree, "pagerank": c.pagerank},
                    )
                ],
                deterministic_signals={
                    "in_degree": c.in_degree,
                    "out_degree": c.out_degree,
                    "pagerank": c.pagerank,
                },
                status=FindingStatus.OBSERVED,
            )
        )
    return findings


# ------------------------- dependency ------------------------------------

def dependency_node(state: RunState, settings: Settings, agent_factory=None) -> dict:
    agent = "dependency"

    def body() -> NodeResult:
        if not _is_enabled(state, agent):
            return NodeResult(NodeStatus.SKIPPED, reason=_skip_reason(state, agent))
        dep_agent = (agent_factory or (lambda: DependencyRiskAgent(settings)))()
        try:
            report = dep_agent.analyze(
                Path(state["workdir"]), state.get("manifest_files") or []
            )
            findings = dep_agent.to_findings(report)
        finally:
            dep_agent.close()
        status = NodeStatus.COMPLETE if findings else NodeStatus.NO_FINDING
        return NodeResult(
            status,
            update={"dependency_report": report, "findings": findings},
            tool_calls=len(report.dependencies),
        )

    return run_node(agent, body)


# ------------------------- git history -----------------------------------

def git_history_node(state: RunState, settings: Settings) -> dict:
    agent = "git_history"

    def body() -> NodeResult:
        if not _is_enabled(state, agent):
            return NodeResult(NodeStatus.SKIPPED, reason=_skip_reason(state, agent))
        gh = GitHistoryAgent(settings)
        report, commits = gh.analyze(Path(state["workdir"]), state["revision"])
        findings = gh.to_findings(report, commits)
        status = NodeStatus.COMPLETE if findings else NodeStatus.NO_FINDING
        return NodeResult(
            status,
            update={"ownership_report": report, "findings": findings},
            tool_calls=report.commits_analyzed,
        )

    return run_node(agent, body)


# ------------------------- normalization (task 4.5) ----------------------

def normalize_node(state: RunState) -> dict:
    """Canonicalize the accumulated findings.

    Findings arrive already as validated ``Finding`` models (the reducer just
    concatenates them). Here we de-duplicate by (agent, category, title) and
    assign a stable ordering, keeping the highest-confidence duplicate.
    """
    findings = state.get("findings") or []
    best: dict[tuple[str, str, str], Finding] = {}
    for f in findings:
        key = (f.agent, f.category, f.title)
        existing = best.get(key)
        if existing is None or f.confidence > existing.confidence:
            best[key] = f

    severity_rank = {
        "critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4,
    }
    canonical = sorted(
        best.values(),
        key=lambda f: (severity_rank.get(f.severity, 9), -f.confidence),
    )
    # Overwrite findings with the canonical list. We can't "reset" an
    # operator.add channel by returning a list (it would append), so we store
    # the canonical set under artifacts and expose via a dedicated key.
    return {
        "artifacts": {**(state.get("artifacts") or {}),
                      "normalized_findings": [f.model_dump() for f in canonical]},
        "node_status": {"normalize": NodeStatus.COMPLETE.value},
    }


# ------------------------- coverage (Phase 5) ----------------------------

def coverage_node(state: "RunState", settings: "Settings", agent_factory=None) -> dict:
    """Run the test suite in the sandbox and emit coverage-gap findings.

    Depends on the architecture graph in state for centrality cross-reference
    (task 5.4). Skips-with-reason when disabled by the manager, when no runner
    is discoverable, or when the sandbox is unavailable (task 5.5).
    """
    from app.analyzers.coverage.agent import CoverageGapAgent
    from app.sandbox.models import SandboxStatus

    agent = "coverage"

    def body() -> "NodeResult":
        if not _is_enabled(state, agent):
            return NodeResult(NodeStatus.SKIPPED, reason=_skip_reason(state, agent))

        cov_agent = (agent_factory or (lambda: CoverageGapAgent(settings)))()
        result = cov_agent.run(Path(state["workdir"]))

        # Skip-with-reason states (task 5.5).
        if result.status in (SandboxStatus.NO_RUNNER, SandboxStatus.UNAVAILABLE):
            reason = CoverageGapAgent.skip_reason(result)
            return NodeResult(
                NodeStatus.SKIPPED,
                update={"coverage": result.model_dump()},
                reason=reason,
            )

        architecture = state.get("architecture")
        findings = cov_agent.to_findings(result, architecture)
        status = NodeStatus.COMPLETE if findings else NodeStatus.NO_FINDING
        return NodeResult(
            status,
            update={"coverage": result.model_dump(), "findings": findings},
            tool_calls=1,
        )

    return run_node(agent, body)


# ------------------------- reasoning (Phase 6) ---------------------------

def reason_node(state: "RunState") -> dict:
    """Evidence validation -> conflict resolution -> risk scoring -> correlation.

    Runs after normalization. Deterministic and reproducible: scoring never
    calls an LLM. Produces:
      * validated/disputed status transitions on findings,
      * preserved conflicts (resolved + unresolved) in state,
      * scored + correlated tech-debt view in artifacts.
    """
    from pathlib import Path as _Path

    from app.reasoning.conflict import ConflictResolver
    from app.reasoning.correlation import correlate_findings
    from app.reasoning.evidence_store import build_evidence_store
    from app.reasoning.risk import RiskScorer
    from app.reasoning.validation import EvidenceValidator

    findings = list(state.get("findings") or [])
    if not findings:
        return {"node_status": {"reason": NodeStatus.NO_FINDING.value}}

    workdir = state.get("workdir")
    validator = EvidenceValidator(repo_root=_Path(workdir) if workdir else None)
    validated, val_outcomes = validator.validate(findings)

    resolver = ConflictResolver()
    resolution = resolver.resolve(validated)

    scorer = RiskScorer()
    scored = scorer.score_all(resolution.findings)
    groups = correlate_findings(scored)

    store = build_evidence_store(resolution.findings)

    tech_debt = [
        {
            "finding_id": s.finding.id,
            "title": s.finding.title,
            "agent": s.finding.agent,
            "category": s.finding.category,
            "severity": s.finding.severity,
            "status": s.finding.status,
            "score": s.score,
            "contributing_signals": s.contributing_signals,
            "explanation": s.explanation,
        }
        for s in scored
    ]
    correlation_view = [
        {
            "component": g.component,
            "group_score": g.group_score,
            "categories": g.categories,
            "finding_ids": g.finding_ids,
        }
        for g in groups
    ]
    conflict_view = [
        {
            "component": c.component,
            "finding_ids": c.finding_ids,
            "resolved": c.resolved,
            "winner_id": c.winner_id,
            "reason": c.reason,
        }
        for c in resolution.conflicts
    ]
    validation_view = [
        {
            "finding_id": o.finding_id,
            "previous_status": o.previous_status,
            "new_status": o.new_status,
            "reason": o.reason,
        }
        for o in val_outcomes
    ]

    return {
        "conflicts": conflict_view,
        "artifacts": {
            **(state.get("artifacts") or {}),
            # Authoritative post-reasoning findings (validated/disputed statuses
            # applied). The top-level append-only `findings` channel keeps the
            # raw specialist outputs; this is the reasoned canonical set.
            "reasoned_findings": [f.model_dump() for f in resolution.findings],
            "tech_debt_ranked": tech_debt,
            "correlation_groups": correlation_view,
            "validation_outcomes": validation_view,
            "evidence_components": store.components(),
        },
        "node_status": {"reason": NodeStatus.COMPLETE.value},
    }


# ------------------------- synthesis (Phase 7) ---------------------------

def synthesis_node(state: "RunState") -> dict:
    """Assemble onboarding + tech-debt artifacts from validated findings.

    Deterministic: no fabrication, unavailable != clean, every claim carries a
    claim_type and (for tech-debt) per-finding attribution (tasks 7.2/7.3/7.5/
    7.6). Artifacts are keyed by revision for persistence (task 7.7).
    """
    from app.synthesis.agent import SynthesisAgent

    agent = SynthesisAgent()
    onboarding = agent.build_onboarding(state)
    tech_debt = agent.build_tech_debt_report(state)

    return {
        "artifacts": {
            **(state.get("artifacts") or {}),
            "onboarding": onboarding,
            "tech_debt_report": tech_debt,
            "artifacts_revision": state.get("revision"),
        },
        "node_status": {"synthesis": NodeStatus.COMPLETE.value},
    }
