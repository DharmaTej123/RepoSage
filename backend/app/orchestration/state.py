"""LangGraph RunState + reducers (task 4.1, 4.6, 4.9).

The state is a ``TypedDict`` (LangGraph's native state container). Append-only
collections use ``operator.add`` reducers so that parallel specialist nodes can
each contribute findings / evidence / metrics without clobbering one another.

Deterministic analyzer outputs (architecture graph, dependency report,
ownership report, coverage) are single-writer, so they use last-write-wins
(plain assignment) — only one node writes each.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, TypedDict

from app.analyzers.dependencies.models import DependencyReport
from app.analyzers.githistory.models import OwnershipReport
from app.analyzers.models import ArchitectureGraph
from app.schemas.finding import Finding


class NodeStatus(str, Enum):
    """Explicit per-node outcome (task 4.9)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"        # ran and produced result(s)
    NO_FINDING = "no_finding"    # ran successfully, nothing notable
    SKIPPED = "skipped"          # manager chose not to run it
    NOT_APPLICABLE = "not_applicable"  # cannot apply to this repo
    FAILED = "failed"            # ran but errored


class AgentMetricRecord(TypedDict, total=False):
    """Per-node observability record (task 4.6)."""

    agent: str
    status: str            # NodeStatus value
    started_at: str | None
    ended_at: str | None
    latency_ms: int | None
    tool_calls: int
    retries: int
    llm_tokens: int
    error: str | None
    reason: str | None     # for skipped / not_applicable


def _merge_status(
    left: dict[str, str], right: dict[str, str]
) -> dict[str, str]:
    merged = dict(left)
    merged.update(right)
    return merged


class RunState(TypedDict, total=False):
    # --- identity / inputs ---
    run_id: str
    repo_id: str
    job_id: str
    workdir: str
    revision: str
    language: str
    manifest_files: list[str]
    objective: str | None

    # --- manager plan (task 4.2 / 4.4) ---
    plan: dict[str, Any]              # {"enabled": [...], "skipped": {name: reason}}

    # --- deterministic analyzer outputs (single-writer) ---
    architecture: ArchitectureGraph | None
    dependency_report: DependencyReport | None
    ownership_report: OwnershipReport | None
    coverage: dict[str, Any] | None

    # --- append-only collections (parallel-safe reducers) ---
    findings: Annotated[list[Finding], operator.add]
    agent_metrics: Annotated[list[AgentMetricRecord], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
    conflicts: Annotated[list[dict[str, Any]], operator.add]

    # --- coarse per-node status map (merge) ---
    node_status: Annotated[dict[str, str], _merge_status]

    # --- generated artifacts (synthesis, later phases) ---
    artifacts: dict[str, Any]


def make_initial_state(
    *,
    run_id: str,
    repo_id: str,
    job_id: str,
    workdir: str,
    revision: str,
    language: str,
    manifest_files: list[str],
    objective: str | None = None,
) -> RunState:
    return RunState(
        run_id=run_id,
        repo_id=repo_id,
        job_id=job_id,
        workdir=workdir,
        revision=revision,
        language=language,
        manifest_files=list(manifest_files),
        objective=objective,
        plan={},
        architecture=None,
        dependency_report=None,
        ownership_report=None,
        coverage=None,
        findings=[],
        agent_metrics=[],
        errors=[],
        conflicts=[],
        node_status={},
        artifacts={},
    )
