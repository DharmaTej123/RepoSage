"""Phase 9 API completion tests (results/graph/findings/query/history/idempotency).

Runs against SQLite + synchronous in-process queue (Redis/Neo4j unavailable ->
graceful fallbacks). Repo code is not executed (no sandbox / Docker), so
coverage self-skips; the pipeline still completes through synthesis.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git import Actor, Repo


def _client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())


@pytest.fixture
def analyzed_job(tmp_env, tmp_path: Path):
    root = tmp_path / "apirepo"
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

    client = _client()
    with client:
        r = client.post("/runs", json={"repo_path": str(root)})
        assert r.status_code == 202, r.text
        body = r.json()
        yield client, body, str(root)


def test_results_endpoint(analyzed_job):
    client, body, _root = analyzed_job
    job_id = body["job_id"]
    r = client.get(f"/runs/{job_id}/results")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "complete"
    assert "findings" in data
    assert "artifacts" in data
    # onboarding + tech-debt artifacts persisted
    assert "onboarding" in data["artifacts"]
    assert "tech_debt_report" in data["artifacts"]
    # analysis completeness exposed explicitly (task 9.5)
    assert "analysis" in data
    assert "skipped" in data["analysis"]


def test_finding_detail_endpoint(analyzed_job):
    client, body, _root = analyzed_job
    job_id = body["job_id"]
    results = client.get(f"/runs/{job_id}/results").json()
    if not results["findings"]:
        pytest.skip("no findings produced for this repo")
    fid = results["findings"][0]["id"]
    r = client.get(f"/runs/{job_id}/findings/{fid}")
    assert r.status_code == 200
    f = r.json()
    assert f["id"] == fid
    assert "evidence" in f


def test_finding_detail_404(analyzed_job):
    client, body, _root = analyzed_job
    r = client.get(f"/runs/{body['job_id']}/findings/does-not-exist")
    assert r.status_code == 404


def test_graph_endpoint_reports_availability(analyzed_job):
    client, body, _root = analyzed_job
    r = client.get(f"/runs/{body['job_id']}/graph")
    assert r.status_code == 200
    data = r.json()
    # Graph not embedded in artifacts by default -> available flag false + note.
    assert data["available"] is False
    assert data["note"]


def test_query_endpoint_dependency(analyzed_job):
    client, body, _root = analyzed_job
    r = client.post(f"/runs/{body['job_id']}/query",
                    json={"question": "What depends on pkg.utils?"})
    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "dependency"
    assert data["sources"]
    assert "pkg.core" in data["answer"]


def test_query_endpoint_guardrail(analyzed_job):
    client, body, _root = analyzed_job
    r = client.post(f"/runs/{body['job_id']}/query",
                    json={"question": "Who worked on pkg.nonexistent?"})
    assert r.status_code == 200
    data = r.json()
    assert data["insufficient_evidence"] is True


def test_history_endpoint(analyzed_job):
    client, body, _root = analyzed_job
    repo_id = body["repo_id"]
    r = client.get(f"/repos/{repo_id}/history")
    assert r.status_code == 200
    data = r.json()
    assert data["repo_id"] == repo_id
    assert len(data["runs"]) >= 1


def test_idempotent_resubmit_reuses_completed_run(analyzed_job):
    client, body, root = analyzed_job
    # First submission already completed. Resubmit same repo (same revision).
    r2 = client.post("/runs", json={"repo_path": root})
    assert r2.status_code == 202
    body2 = r2.json()
    status2 = client.get(f"/runs/{body2['job_id']}/status").json()
    assert status2["status"] == "complete"
    assert "idempotent" in (status2["agent_status"] or {})