"""Coverage Gap Agent + sandbox tests (Phase 5).

Docker is not required: these tests use a fake runner and the Unavailable path.
Live Docker isolation (network-block) is validated in Phase 12 when Docker is
available (task 5.7 / 12.2).
"""

from __future__ import annotations

from pathlib import Path

from app.analyzers.architecture_mapper import ArchitectureMapper
from app.analyzers.coverage.agent import CoverageGapAgent
from app.config import Settings
from app.sandbox.coverage_parser import module_id_for, parse_coverage_json
from app.sandbox.models import SandboxResult, SandboxStatus
from app.sandbox.runner import (
    LocalSubprocessRunner,
    UnavailableSandboxRunner,
    get_sandbox_runner,
    has_discoverable_tests,
)


# ------------------------- coverage parser -------------------------------

def test_module_id_for():
    assert module_id_for("pkg/core.py") == "pkg.core"
    assert module_id_for("pkg/__init__.py") == "pkg"
    assert module_id_for("readme.md") is None


def test_parse_coverage_json():
    data = {
        "files": {
            "pkg/core.py": {"summary": {"percent_covered": 40.0}},
            "pkg/utils.py": {"summary": {"percent_covered": 95.0}},
        },
        "totals": {"percent_covered": 67.5},
    }
    by_mod, total = parse_coverage_json(data)
    assert by_mod["pkg.core"] == 0.4
    assert by_mod["pkg.utils"] == 0.95
    assert total == 0.675


# ------------------------- fake runner -----------------------------------

class FakeRunner:
    def __init__(self, result: SandboxResult):
        self._result = result

    def run_coverage(self, repo_root: Path) -> SandboxResult:
        return self._result


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
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
    return root


def test_coverage_gap_findings_from_centrality(tmp_path: Path):
    root = _repo(tmp_path)
    arch = ArchitectureMapper(root, revision="rev").run()

    # utils is highly central; give it LOW coverage to trigger a gap finding.
    result = SandboxResult(
        status=SandboxStatus.COMPLETED, exit_code=0, coverage_available=True,
        coverage_by_file={"pkg.utils": 0.2, "pkg.core": 0.9, "pkg.service": 0.95},
        total_coverage=0.6, backend="fake",
    )
    agent = CoverageGapAgent(Settings(), runner=FakeRunner(result))
    findings = agent.to_findings(result, arch)

    gaps = [f for f in findings if f.category == "coverage_gap"]
    assert any("pkg.utils" in f.affected_components for f in gaps)
    f = next(f for f in gaps if "pkg.utils" in f.affected_components)
    assert any(e.source_type == "command" for e in f.evidence)
    assert f.deterministic_signals["coverage"] == 0.2


def test_no_coverage_data_no_findings(tmp_path: Path):
    root = _repo(tmp_path)
    arch = ArchitectureMapper(root, revision="rev").run()
    result = SandboxResult(status=SandboxStatus.NO_RUNNER, coverage_available=False)
    agent = CoverageGapAgent(Settings(), runner=FakeRunner(result))
    assert agent.to_findings(result, arch) == []


def test_skip_reason_reported():
    result = SandboxResult(status=SandboxStatus.NO_RUNNER, error="no tests")
    assert CoverageGapAgent.skip_reason(result) == "no tests"
    result2 = SandboxResult(status=SandboxStatus.UNAVAILABLE, error="no docker")
    assert CoverageGapAgent.skip_reason(result2) == "no docker"
    result3 = SandboxResult(status=SandboxStatus.COMPLETED)
    assert CoverageGapAgent.skip_reason(result3) is None


# ------------------------- runner selection ------------------------------

def test_get_sandbox_runner_unavailable_without_docker():
    # Docker daemon is not present in this env -> Unavailable, NOT local.
    runner = get_sandbox_runner(Settings())
    assert isinstance(runner, UnavailableSandboxRunner)
    result = runner.run_coverage(Path("."))
    assert result.status == SandboxStatus.UNAVAILABLE


def test_local_runner_refuses_by_default(tmp_path: Path):
    root = _repo(tmp_path)
    runner = LocalSubprocessRunner(Settings(), allow=False)
    result = runner.run_coverage(root)
    assert result.status == SandboxStatus.UNAVAILABLE
    assert "outside a sandbox" in (result.error or "")


def test_has_discoverable_tests(tmp_path: Path):
    root = tmp_path / "r"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    assert has_discoverable_tests(root) is True

    root2 = tmp_path / "r2"
    root2.mkdir()
    (root2 / "a.py").write_text("x=1\n", encoding="utf-8")
    assert has_discoverable_tests(root2) is False