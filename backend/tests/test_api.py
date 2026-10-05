"""API flow tests (tasks 0.1 / 0.3, Req 1, 12)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def test_health(tmp_env):
    with _client() as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_submit_and_status(tmp_env, sample_python_repo: Path):
    with _client() as client:
        r = client.post("/runs", json={"repo_path": str(sample_python_repo)})
        assert r.status_code == 202, r.text
        body = r.json()
        job_id = body["job_id"]
        # Synchronous in-process queue runs the pipeline inline in tests, so the
        # job reaches a terminal state (complete) by the time we get the response.
        assert body["status"] in {"pending", "running", "complete"}

        s = client.get(f"/runs/{job_id}/status")
        assert s.status_code == 200
        status_body = s.json()
        assert status_body["status"] in {"pending", "complete"}
        assert status_body["repository"]["language"] == "python"
        assert len(status_body["revision"]) == 40


def test_submit_requires_exactly_one_source(tmp_env):
    with _client() as client:
        r = client.post("/runs", json={})
        assert r.status_code == 422


def test_submit_bad_path_marks_job_failed(tmp_env):
    with _client() as client:
        r = client.post("/runs", json={"repo_path": "/nonexistent/path/xyz"})
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        s = client.get(f"/runs/{job_id}/status").json()
        assert s["status"] == "failed"
        assert s["error"]


def test_status_404_for_unknown_job(tmp_env):
    with _client() as client:
        r = client.get("/runs/does-not-exist/status")
        assert r.status_code == 404
