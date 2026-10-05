"""End-to-end validation tests (Phase 12: 12.3, 12.4, 12.5, 12.6).

These validate cross-cutting pipeline behaviors without needing Docker:
* checkpoint/resume without rerunning completed nodes,
* partial-failure isolation (one specialist down),
* conflict-resolution preserving unresolved conflicts,
* evidence citations on the final onboarding/tech-debt output.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from git import Actor, Repo
from langgraph.checkpoint.memory import MemorySaver

from app.config import Settings
from app.orchestration.graph import build_graph, run_workflow
from app.orchestration.state import make_initial_state


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("e2e") / "repo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "core.py").write_text(
        "from pkg import utils\n\n\ndef run():\n    return utils.helper()\n",
        encoding="utf-8",
    )
    (pkg / "service.py").write_text(
        "from pkg import core, utils\n\n\ndef serve():\n    return core.run()\n",
        encoding="utf-8",
    )
    r = Repo.init(root)
    r.index.add(["pkg/__init__.py", "pkg/utils.py", "pkg/core.py", "pkg/service.py"])
    a = Actor("Alice", "alice@example.com")
    r.index.commit("init", author=a, committer=a)
    r.close()
    return root


def _state(repo: Path, run_id="e2e"):
    return make_initial_state(
        run_id=run_id, repo_id="rp", job_id="j", workdir=str(repo),
        revision="rev", language="python", manifest_files=[],
    )


# --- 12.3 checkpoint / resume -------------------------------------------

def test_checkpoint_resume_does_not_rerun_completed_nodes(repo: Path):
    saver = MemorySaver()
    graph = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "resume-e2e"}}
    final = graph.invoke(_state(repo), config=cfg)
    assert final["node_status"]["synthesis"] == "complete"

    # Resuming an already-finished thread returns the persisted terminal state
    # without re-executing (the checkpoint holds the completed values).
    snapshot = graph.get_state(cfg)
    assert snapshot.values["node_status"]["synthesis"] == "complete"
    assert snapshot.next == ()  # nothing left to run


# --- 12.4 partial failure isolation -------------------------------------

def test_partial_failure_one_specialist_down(repo: Path, monkeypatch):
    import app.orchestration.nodes as nodes_mod
    from app.orchestration.node_utils import NodeResult, run_node
    from app.orchestration.state import RunState

    def broken_dependency(state: RunState, settings, agent_factory=None):
        def body() -> NodeResult:
            raise RuntimeError("dependency analyzer unavailable")
        return run_node("dependency", body, max_attempts=1)

    monkeypatch.setattr(nodes_mod, "dependency_node", broken_dependency)

    final = run_workflow(_state(repo, "partial"))
    # Failed specialist recorded, but the run still completes through synthesis.
    assert final["node_status"]["dependency"] == "failed"
    assert final["node_status"]["synthesis"] == "complete"
    assert any(f.agent == "architecture" for f in final["findings"])
    assert any(e["agent"] == "dependency" for e in final["errors"])


# --- 12.5 conflict resolution -------------------------------------------

def test_conflict_resolution_preserves_unresolved(repo: Path, monkeypatch):
    """Inject a contradictory finding pair and confirm the reason node keeps
    the unresolved conflict rather than silently dropping one."""
    import app.orchestration.nodes as nodes_mod
    from app.orchestration.node_utils import NodeResult, run_node
    from app.orchestration.state import NodeStatus, RunState
    from app.schemas.finding import (
        Evidence, EvidenceSourceType, Finding, FindingSeverity,
    )

    def ev():
        return [Evidence(source_type=EvidenceSourceType.GRAPH, source="module:pkg.core")]

    def conflicting_arch(state: RunState, settings):
        def body() -> NodeResult:
            a = Finding(agent="architecture", category="high_centrality",
                        title="central", severity=FindingSeverity.INFO,
                        confidence=0.8, description="d",
                        affected_components=["pkg.core"], evidence=ev())
            b = Finding(agent="architecture", category="isolated_module",
                        title="isolated", severity=FindingSeverity.INFO,
                        confidence=0.8, description="d",
                        affected_components=["pkg.core"], evidence=ev())
            return NodeResult(NodeStatus.COMPLETE, update={"findings": [a, b]})
        return run_node("architecture", body)

    monkeypatch.setattr(nodes_mod, "architecture_node", conflicting_arch)

    final = run_workflow(_state(repo, "conflict"))
    conflicts = final.get("conflicts") or []
    assert any(c["resolved"] is False for c in conflicts)
    # Both findings preserved (none dropped). The authoritative post-reasoning
    # statuses live in artifacts.reasoned_findings.
    reasoned = final["artifacts"]["reasoned_findings"]
    core = [f for f in reasoned if "pkg.core" in (f.get("affected_components") or [])]
    assert len(core) >= 2
    assert any(f["status"] == "disputed" for f in core)


# --- 12.6 evidence citations on final output ----------------------------

def test_final_output_claims_carry_evidence_or_inference(repo: Path):
    final = run_workflow(_state(repo, "evidence"))
    art = final["artifacts"]

    # Tech-debt items each carry attribution + a claim_type.
    items = art["tech_debt_report"]["items"]
    for item in items:
        assert "claim_type" in item
        if item["claim_type"] == "observed":
            assert item["attribution"], f"observed item lacks attribution: {item['title']}"

    # Onboarding claims are typed (observed vs inferred) and carry an evidence tag.
    for entry in art["onboarding"]["reading_order"]:
        assert entry["claim_type"] in ("observed", "inferred")
        assert entry.get("evidence")

    # Analysis status distinguishes unavailable from clean (no fabricated clean).
    status = art["tech_debt_report"]["analysis_status"]
    assert set(status.values()) <= {"complete", "clean", "unavailable", "failed"}