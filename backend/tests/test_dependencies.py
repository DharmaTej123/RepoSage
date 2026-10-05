"""Dependency Risk agent tests (Phase 2). External HTTP is mocked."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.analyzers.dependencies.agent import DependencyRiskAgent
from app.analyzers.dependencies.manifest import parse_manifests
from app.analyzers.dependencies.models import VulnDataStatus
from app.analyzers.dependencies.osv_client import OSVClient, OSVUnavailableError
from app.analyzers.dependencies.pypi_client import PyPIClient
from app.config import Settings


# ------------------------- manifest parsing -----------------------------

def test_parse_requirements_txt(tmp_path: Path):
    root = tmp_path
    (root / "requirements.txt").write_text(
        "requests==2.31.0\n"
        "flask>=2.0  # web\n"
        "# a comment\n"
        "-r other.txt\n"
        "django==4.2.1\n",
        encoding="utf-8",
    )
    deps = parse_manifests(root, ["requirements.txt"])
    by_name = {d.name: d for d in deps}
    assert by_name["requests"].version == "2.31.0"
    assert by_name["flask"].version is None  # range only -> unpinned
    assert by_name["django"].version == "4.2.1"
    assert "other.txt" not in [d.name for d in deps]


def test_parse_pyproject_pep621_and_poetry(tmp_path: Path):
    root = tmp_path
    (root / "pyproject.toml").write_text(
        """
[project]
dependencies = ["httpx==0.27.0", "pydantic>=2.9"]

[project.optional-dependencies]
dev = ["pytest==8.3.0"]

[tool.poetry.dependencies]
python = "^3.11"
requests = "2.31.0"
rich = { version = "13.7.0" }
""",
        encoding="utf-8",
    )
    deps = parse_manifests(root, ["pyproject.toml"])
    by_name = {d.name: d for d in deps}
    assert by_name["httpx"].version == "0.27.0"
    assert by_name["pydantic"].version is None
    assert by_name["pytest"].version == "8.3.0"
    assert by_name["requests"].version == "2.31.0"
    assert by_name["rich"].version == "13.7.0"
    assert "python" not in by_name


# ------------------------- OSV client ------------------------------------

def _osv_transport(vuln_present: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/querybatch":
            if vuln_present:
                results = [{"vulns": [{"id": "GHSA-test-0001"}]}]
            else:
                results = [{}]
            return httpx.Response(200, json={"results": results})
        if request.url.path.startswith("/v1/vulns/"):
            return httpx.Response(
                200,
                json={
                    "id": "GHSA-test-0001",
                    "summary": "Test vulnerability",
                    "aliases": ["CVE-2024-0001"],
                    "database_specific": {"severity": "HIGH"},
                    "affected": [
                        {"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.31.1"}]}]}
                    ],
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_osv_client_finds_vuln():
    client = httpx.Client(transport=_osv_transport(True))
    osv = OSVClient(client=client)
    results = osv.query_batch([("requests", "2.31.0")])
    assert len(results) == 1
    assert results[0][0].id == "GHSA-test-0001"
    assert results[0][0].severity == "high"
    assert "2.31.1" in results[0][0].fixed_versions


def test_osv_client_clean():
    client = httpx.Client(transport=_osv_transport(False))
    osv = OSVClient(client=client)
    results = osv.query_batch([("requests", "2.31.0")])
    assert results[0] == []


def test_osv_client_unavailable_raises():
    def handler(request):
        raise httpx.ConnectError("boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    osv = OSVClient(client=client)
    with pytest.raises(OSVUnavailableError):
        osv.query_batch([("requests", "2.31.0")])


# ------------------------- PyPI client -----------------------------------

def test_pypi_staleness():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "info": {"version": "1.0.0"},
                "releases": {
                    "1.0.0": [{"upload_time_iso_8601": "2018-01-01T00:00:00Z"}]
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pypi = PyPIClient(client=client)
    rel = pypi.get_release_info("oldpkg", staleness_months=18)
    assert rel.available is True
    assert rel.is_stale is True
    assert rel.latest_version == "1.0.0"


def test_pypi_unavailable_returns_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pypi = PyPIClient(client=client)
    rel = pypi.get_release_info("x", staleness_months=18)
    assert rel.available is False


# ------------------------- agent end-to-end ------------------------------

@pytest.fixture
def repo_with_reqs(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text(
        "requests==2.31.0\nflask>=2.0\n", encoding="utf-8"
    )
    return tmp_path


def _combined_transport(osv_vuln: bool, osv_up: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "api.osv.dev":
            if not osv_up:
                raise httpx.ConnectError("osv down")
            if request.url.path == "/v1/querybatch":
                results = [{"vulns": [{"id": "GHSA-x"}]}] if osv_vuln else [{}]
                return httpx.Response(200, json={"results": results})
            if request.url.path.startswith("/v1/vulns/"):
                return httpx.Response(200, json={
                    "id": "GHSA-x", "summary": "vuln",
                    "database_specific": {"severity": "CRITICAL"},
                    "affected": [{"ranges": [{"events": [{"fixed": "2.31.1"}]}]}],
                })
        if host == "pypi.org":
            return httpx.Response(200, json={
                "info": {"version": "2.31.0"},
                "releases": {"2.31.0": [{"upload_time_iso_8601": "2024-06-01T00:00:00Z"}]},
            })
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_agent_vulnerable_produces_finding(repo_with_reqs: Path):
    settings = Settings()
    client = httpx.Client(transport=_combined_transport(osv_vuln=True))
    agent = DependencyRiskAgent(
        settings, osv_client=OSVClient(client=client), pypi_client=PyPIClient(client=client)
    )
    report = agent.analyze(repo_with_reqs, ["requirements.txt"])

    by_name = {r.dependency.name: r for r in report.dependencies}
    assert by_name["requests"].vuln_status == VulnDataStatus.VULNERABLE
    # flask is unpinned -> UNPINNED, not CLEAN or UNAVAILABLE
    assert by_name["flask"].vuln_status == VulnDataStatus.UNPINNED

    findings = agent.to_findings(report)
    vuln_findings = [f for f in findings if f.category == "vulnerable_dependency"]
    assert len(vuln_findings) == 1
    f = vuln_findings[0]
    assert f.severity == "critical"
    # external-source provenance present
    assert any(e.source_type == "external_api" for e in f.evidence)
    assert f.recommendation


def test_agent_clean_distinct_from_unavailable(repo_with_reqs: Path):
    settings = Settings()
    client = httpx.Client(transport=_combined_transport(osv_vuln=False))
    agent = DependencyRiskAgent(
        settings, osv_client=OSVClient(client=client), pypi_client=PyPIClient(client=client)
    )
    report = agent.analyze(repo_with_reqs, ["requirements.txt"])
    by_name = {r.dependency.name: r for r in report.dependencies}
    assert by_name["requests"].vuln_status == VulnDataStatus.CLEAN
    assert report.osv_unavailable is False


def test_agent_osv_unavailable_degrades(repo_with_reqs: Path):
    settings = Settings()
    client = httpx.Client(transport=_combined_transport(osv_vuln=False, osv_up=False))
    agent = DependencyRiskAgent(
        settings, osv_client=OSVClient(client=client), pypi_client=PyPIClient(client=client)
    )
    report = agent.analyze(repo_with_reqs, ["requirements.txt"])
    assert report.osv_unavailable is True
    by_name = {r.dependency.name: r for r in report.dependencies}
    # pinned dep becomes UNAVAILABLE (not CLEAN)
    assert by_name["requests"].vuln_status == VulnDataStatus.UNAVAILABLE
    findings = agent.to_findings(report)
    assert any(f.category == "analysis_gap" for f in findings)
