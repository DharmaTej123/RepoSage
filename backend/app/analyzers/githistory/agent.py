"""Git History & Ownership orchestration (tasks 3.4-3.6).

Produces:
* an :class:`OwnershipReport` (deterministic per-module contribution/churn),
* structured :class:`Finding`s for bus-factor concentration, each with git
  provenance (commit shas / author) and deterministic signals,
* Developer -> Commit -> Module graph nodes/edges for historical-ownership
  queries (design.md section 5).

Language discipline (Req 4): output uses "historical contributor" /
"contribution concentration", never "owner".
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analyzers.githistory.miner import GitHistoryMiner, file_to_module
from app.analyzers.githistory.models import CommitRecord, OwnershipReport
from app.analyzers.models import GraphEdge, GraphNode, NodeKind, RelKind
from app.config import Settings
from app.schemas.finding import (
    Evidence,
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "git_history"


class GitHistoryAgent:
    def __init__(self, settings: Settings):
        self._settings = settings

    def analyze(self, repo_root: Path, revision: str) -> tuple[OwnershipReport, list[CommitRecord]]:
        miner = GitHistoryMiner(repo_root, self._settings.history_window_days)
        commits = miner.mine()
        modules = miner.aggregate(commits, self._settings.bus_factor_threshold)

        report = OwnershipReport(
            revision=revision,
            window_days=self._settings.history_window_days,
            commits_analyzed=len(commits),
            modules=modules,
            limited=(len(commits) == 0),
        )
        if not commits:
            report.notes.append(
                "No commits found in the configured history window; ownership "
                "analysis is limited."
            )
        return report, commits

    # --- findings (task 3.6) --------------------------------------------
    def to_findings(self, report: OwnershipReport, commits: list[CommitRecord]) -> list[Finding]:
        findings: list[Finding] = []
        # Index recent commit shas per module for provenance.
        module_commits = self._module_commit_index(commits)

        for m in report.modules:
            if not m.bus_factor_flag:
                continue
            shas = module_commits.get(m.module, [])[:5]
            evidence = [
                Evidence(
                    source_type=EvidenceSourceType.GIT,
                    source=f"commit:{sha}",
                    location=m.module,
                )
                for sha in shas
            ]
            if not evidence:
                # Should not happen for a flagged module, but stay safe: fall
                # back to a git-source evidence referencing the module history.
                evidence = [
                    Evidence(
                        source_type=EvidenceSourceType.GIT,
                        source=f"git-history:{m.module}",
                    )
                ]
            findings.append(
                Finding(
                    agent=AGENT_NAME,
                    category="bus_factor",
                    title=f"Contribution concentration in {m.module}",
                    severity=FindingSeverity.MEDIUM,
                    confidence=0.8,
                    description=(
                        f"{m.primary_contributor} authored "
                        f"{m.primary_contributor_share:.0%} of the {m.total_commits} "
                        f"recent commits touching '{m.module}'. This indicates "
                        f"historical contribution concentration (a knowledge / "
                        f"bus-factor risk), not formal ownership."
                    ),
                    affected_components=[m.module],
                    evidence=evidence,
                    recommendation=(
                        "Spread review and changes for this module across more "
                        "contributors and add documentation to reduce knowledge "
                        "concentration."
                    ),
                    deterministic_signals=m.as_signals(),
                    status=FindingStatus.OBSERVED,
                )
            )
        return findings

    # --- graph relationships (task 3.4) ---------------------------------
    def to_graph(self, commits: list[CommitRecord]) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Developer -> Commit -> Module nodes/edges for ownership queries."""
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        for c in commits:
            dev_id = f"dev:{c.author_email.lower()}"
            commit_id = f"commit:{c.sha}"
            nodes.setdefault(
                dev_id,
                GraphNode(
                    id=dev_id, kind=NodeKind.DEVELOPER, name=c.author_name,
                    metadata={"email": c.author_email},
                ),
            )
            nodes.setdefault(
                commit_id,
                GraphNode(
                    id=commit_id, kind=NodeKind.COMMIT, name=c.sha[:12],
                    metadata={"authored_at": c.authored_at.isoformat()},
                ),
            )
            edges.append(
                GraphEdge(source=dev_id, target=commit_id, kind=RelKind.AUTHORED)
            )
            touched_modules = {
                m for f in c.changed_files if (m := file_to_module(f)) is not None
            }
            for module in touched_modules:
                edges.append(
                    GraphEdge(
                        source=commit_id, target=module, kind=RelKind.TOUCHED,
                        metadata={"sha": c.sha},
                    )
                )
        return list(nodes.values()), edges

    @staticmethod
    def _module_commit_index(commits: list[CommitRecord]) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for c in commits:  # commits are newest-first from the miner
            for f in c.changed_files:
                module = file_to_module(f)
                if module is None:
                    continue
                idx.setdefault(module, []).append(c.sha)
        return idx
