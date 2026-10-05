"""LangGraph orchestration tests (Phase 4)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from git import Actor, Repo
from langgraph.checkpoint.memory import MemorySaver

from app.analyzers.dependencies.agent import DependencyRiskAgent
from app.analyzers.dependencies.osv_client import OSVClient
from app.analyzers.dependencies.pypi_client import PyPIClient
from app.config import Settings, get_settings
from app.orchestration.graph import build_graph, run_workflow
from app.orchestration.manager import plan_investigation
from app.orchestration.node_utils import NodeResult, TransientToolError, run_node
from app.orchestration.state import NodeStatus, make_initial_state


ALICE = Actor("Alice", "alice@example.com")


@pytest.fixture(scope="module")
def analysis_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("orch") / "repo"
    pkg = root / "pkg"
    tests_dir = root / "tests"
    pkg.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "core.py").write_text(
        "from pkg import utils\n\n\nclass Engine:\n    def run(self):\n        return utils.helper()\n",
        encoding="utf-8",
    )
    (pkg / "service.py").write_text(
        "from pkg import core, utils\n\n\ndef serve():\n    return core.Engine().run() + utils.helper()\n",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    (tests_dir / "test_utils.py").write_text(
        "from pkg import utils\n\n\ndef test_helper():\n    assert utils.helper() == 1\n",
        encoding="utf-8",
    )

    repo = Repo.init(root)
    repo.index.add([
        "pkg/__init__.py", "pkg/utils.py", "pkg/core.py", "pkg/service.py",
        "requirements.txt", "tests/test_utils.py",
    ])
    repo.index.commit("init", author=ALICE, committer=ALICE)
    return root


def _initial(repo: Path, revision: str = "rev1", objective=None):
    return make_initial_state(
        run_id="run-1", repo_id="repo-1", job_id="job-1",
        workdir=str(repo), revision=revision, language="python",
        manifest_files=["requirements.txt"], objective=objective,
    )


def _dep_factory():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.osv.dev":
            return httpx.Response(200, json={"results": [{}]})
        if request.url.host == "pypi.org":
            return httpx.Response(200, json={
                "info": {"version": "2.31.0"},
                "releases": {"2.31.0": [{"upload_time_iso_8601": "2024-06-01T00:00:00Z"}]},
            })
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DependencyRiskAgent(
        get_settings(), osv_client=OSVClient(client=client),
        pypi_client=PyPIClient(client=client),
    )


def test_run_node_records_metric_and_status():
    def body() -> NodeResult:
        return NodeResult(NodeStatus.COMPLETE, update={"findings": []}, tool_calls=2)

    out = run_node("x", body)
    assert out["node_status"] == {"x": "complete"}
    assert out["agent_metrics"][0]["tool_calls"] == 2
    assert out["agent_metrics"][0]["retries"] == 0


def test_run_node_retries_transient_then_fails():
    calls = {"n": 0}

    def body() -> NodeResult:
        calls["n"] += 1
        raise TransientToolError("nope")

    out = run_node("x", body, max_attempts=3)
    assert calls["n"] == 3
    assert out["node_status"] == {"x": "failed"}
    assert out["agent_metrics"][0]["retries"] == 2
    assert out["errors"][0]["agent"] == "x"


def test_run_node_retry_then_success():
    calls = {"n": 0}

    def body() -> NodeResult:
        calls["n"] += 1
        if calls["n"] < 2:
            raise TransientToolError("retry me")
        return NodeResult(NodeStatus.COMPLETE)

    out = run_node("x", body, max_attempts=3)
    assert out["node_status"] == {"x": "complete"}
    assert out["agent_metrics"][0]["retries"] == 1


def test_manager_enables_applicable_workflows(analysis_repo: Path):
    state = _initial(analysis_repo)
    plan = plan_investigation(state)
    assert set(plan["enabled"]) == {"architecture", "dependency", "git_history", "coverage"}
    assert plan["skipped"] == {}


def test_manager_skips_missing_inputs(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    state = make_initial_state(
        run_id="r", repo_id="rp", job_id="j", workdir=str(empty),
        revision="x", language="unknown", manifest_files=[],
    )
    plan = plan_investigation(state)
    assert "architecture" not in plan["enabled"]
    assert set(plan["skipped"]) == {"architecture", "dependency", "git_history", "coverage"}


def test_end_to_end_run(analysis_repo: Path, monkeypatch):
    import app.orchestration.nodes as nodes_mod

    original = nodes_mod.dependency_node

    def patched_dep(state, settings, agent_factory=None):
        return original(state, settings, agent_factory=_dep_factory)

    monkeypatch.setattr(nodes_mod, "dependency_node", patched_dep)

    settings = Settings()
    settings.bus_factor_threshold = 0.5
    final = run_workflow(_initial(analysis_repo), settings=settings)

    status = final["node_status"]
    assert status["manager"] == "complete"
    assert status["architecture"] in ("complete", "no_finding")
    assert status["git_history"] in ("complete", "no_finding")
    assert status["normalize"] == "complete"

    arch_findings = [f for f in final["findings"] if f.agent == "architecture"]
    assert any("pkg.utils" in f.affected_components for f in arch_findings)

    assert "normalized_findings" in final["artifacts"]

    agents_with_metrics = {m["agent"] for m in final["agent_metrics"]}
    assert {"architecture", "dependency", "git_history"} <= agents_with_metrics


def test_partial_failure_preserves_other_results(analysis_repo: Path, monkeypatch):
    import app.orchestration.nodes as nodes_mod

    def boom(state, settings):
        from app.orchestration.node_utils import NodeResult, run_node

        def body() -> NodeResult:
            raise RuntimeError("git blew up")

        return run_node("git_history", body, max_attempts=1)

    monkeypatch.setattr(nodes_mod, "git_history_node", boom)

    final = run_workflow(_initial(analysis_repo))
    assert final["node_status"]["git_history"] == "failed"
    assert final["node_status"]["normalize"] == "complete"
    assert any(f.agent == "architecture" for f in final["findings"])
    assert any(e["agent"] == "git_history" for e in final["errors"])


def test_skipping_recorded_with_reason(tmp_path: Path):
    root = tmp_path / "repo2"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    repo = Repo.init(root)
    repo.index.add(["a.py"])
    repo.index.commit("init", author=ALICE, committer=ALICE)

    state = make_initial_state(
        run_id="r2", repo_id="rp2", job_id="j2", workdir=str(root),
        revision="rev", language="python", manifest_files=[],
    )
    final = run_workflow(state)
    assert final["node_status"]["dependency"] == "skipped"
    dep_metric = next(m for m in final["agent_metrics"] if m["agent"] == "dependency")
    assert dep_metric["reason"]


def test_checkpoint_resume(analysis_repo: Path):
    saver = MemorySaver()
    graph = build_graph(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "resume-1"}}
    final = graph.invoke(_initial(analysis_repo), config=cfg)
    assert final["node_status"]["normalize"] == "complete"

    snapshot = graph.get_state(cfg)
    assert snapshot.values["node_status"]["manager"] == "complete"


def test_coverage_node_in_full_run_skips_without_docker(tmp_path):
    """Coverage node self-skips (with reason) when the sandbox is unavailable,
    without failing the run."""
    from git import Actor, Repo
    from app.config import Settings
    from app.orchestration.graph import run_workflow
    from app.orchestration.state import make_initial_state

    root = tmp_path / "covrepo"
    pkg = root / "pkg"
    tests_dir = root / "tests"
    pkg.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_utils.py").write_text(
        "from pkg import utils\n\n\ndef test_h():\n    assert utils.helper() == 1\n",
        encoding="utf-8",
    )
    repo = Repo.init(root)
    repo.index.add(["pkg/__init__.py", "pkg/utils.py", "tests/test_utils.py"])
    a = Actor("Alice", "alice@example.com")
    repo.index.commit("init", author=a, committer=a)

    state = make_initial_state(
        run_id="cov1", repo_id="rp", job_id="j", workdir=str(root),
        revision="rev", language="python", manifest_files=[],
    )
    final = run_workflow(state, settings=Settings())
    # Manager enables coverage (tests exist) but sandbox is unavailable -> skip.
    assert final["node_status"]["coverage"] == "skipped"
    cov_metric = next(m for m in final["agent_metrics"] if m["agent"] == "coverage")
    assert cov_metric["reason"]
    assert final["node_status"]["normalize"] == "complete"


def test_reason_node_in_full_run_produces_tech_debt(tmp_path):
    """After a full run the reason node yields ranked tech-debt + validation."""
    from git import Actor, Repo
    from app.config import Settings
    from app.orchestration.graph import run_workflow
    from app.orchestration.state import make_initial_state

    root = tmp_path / "reasonrepo"
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
    repo = Repo.init(root)
    repo.index.add(["pkg/__init__.py", "pkg/utils.py", "pkg/core.py", "pkg/service.py"])
    a = Actor("Alice", "alice@example.com")
    repo.index.commit("init", author=a, committer=a)

    state = make_initial_state(
        run_id="reason1", repo_id="rp", job_id="j", workdir=str(root),
        revision="rev", language="python", manifest_files=[],
    )
    settings = Settings()
    settings.bus_factor_threshold = 0.5
    final = run_workflow(state, settings=settings)

    assert final["node_status"]["reason"] == "complete"
    art = final["artifacts"]
    assert "tech_debt_ranked" in art
    assert isinstance(art["tech_debt_ranked"], list)
    # Ranked entries carry a score + contributing signals (auditable).
    if art["tech_debt_ranked"]:
        top = art["tech_debt_ranked"][0]
        assert "score" in top and "contributing_signals" in top and "explanation" in top
    assert "correlation_groups" in art
    assert "validation_outcomes" in art


def test_synthesis_node_in_full_run(tmp_path):
    from git import Actor, Repo
    from app.config import Settings
    from app.orchestration.graph import run_workflow
    from app.orchestration.state import make_initial_state

    root = tmp_path / "synthrepo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "core.py").write_text(
        "from pkg import utils\n\n\ndef run():\n    return utils.helper()\n",
        encoding="utf-8",
    )
    repo = Repo.init(root)
    repo.index.add(["pkg/__init__.py", "pkg/utils.py", "pkg/core.py"])
    a = Actor("Alice", "alice@example.com")
    repo.index.commit("init", author=a, committer=a)

    state = make_initial_state(
        run_id="synth1", repo_id="rp", job_id="j", workdir=str(root),
        revision="rev", language="python", manifest_files=[],
    )
    final = run_workflow(state, settings=Settings())
    assert final["node_status"]["synthesis"] == "complete"
    art = final["artifacts"]
    assert "onboarding" in art and "tech_debt_report" in art
    assert art["onboarding"]["reading_order"]  # centrality-based reading order
    assert art["artifacts_revision"] == "rev"
    # git_history skipped or complete -> status reported, never fabricated clean
    assert "analysis_status" in art["tech_debt_report"]
