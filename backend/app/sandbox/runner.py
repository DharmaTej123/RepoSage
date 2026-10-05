"""Sandbox runners (tasks 5.2, 5.5, 5.7, 5.8).

Two implementations behind one protocol:

* ``DockerSandboxRunner`` (production): runs the repo test suite in a container
  started with ``network_disabled=True`` / ``network_mode="none"``, CPU/memory/
  pids limits, a read-only repo mount, an isolated writable scratch tmpfs, no
  host env, and a wall-clock timeout. The container is always removed.

* ``LocalSubprocessRunner`` (DEV ONLY): runs pytest in a subprocess on the host
  with no isolation. It refuses to run unless explicitly allowed, because
  running untrusted code outside the sandbox violates Req 6.

``get_sandbox_runner`` returns the Docker runner when the Docker SDK + daemon
are available, else a runner that reports ``UNAVAILABLE`` (so the pipeline
degrades with a clear reason rather than silently executing code unsafely).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import Settings
from app.sandbox.coverage_parser import parse_coverage_file
from app.sandbox.models import SandboxResult, SandboxStatus

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "reposage-sandbox:latest"


def isolation_run_kwargs(settings: Settings) -> dict:
    """The security boundary for sandboxed execution (Req 6), in one place.

    Both ``DockerSandboxRunner`` and the automated isolation test consume these
    kwargs so the test verifies the *actual* flags applied in production rather
    than a hand-copied approximation that can silently drift.

    Enforces: no outbound network, read-only container fs, dropped capabilities,
    no privilege escalation, and CPU/memory/pids limits.
    """
    return {
        "network_disabled": True,        # no NIC attached
        "network_mode": "none",          # no network namespace
        "read_only": True,               # container root fs is read-only
        "mem_limit": f"{settings.sandbox_memory_mb}m",
        "nano_cpus": int(settings.sandbox_cpu_limit * 1e9),
        "pids_limit": settings.sandbox_pids_limit,
        "cap_drop": ["ALL"],             # drop all Linux capabilities
        "security_opt": ["no-new-privileges"],
    }


def has_discoverable_tests(repo_root: Path) -> bool:
    if (repo_root / "tests").is_dir():
        return True
    for _ in repo_root.rglob("test_*.py"):
        return True
    for _ in repo_root.rglob("*_test.py"):
        return True
    return False


@runtime_checkable
class SandboxRunner(Protocol):
    def run_coverage(self, repo_root: Path) -> SandboxResult: ...


class UnavailableSandboxRunner:
    """Reports UNAVAILABLE. Used when no safe backend exists."""

    def __init__(self, reason: str):
        self._reason = reason

    def run_coverage(self, repo_root: Path) -> SandboxResult:
        return SandboxResult(
            status=SandboxStatus.UNAVAILABLE, backend="none", error=self._reason
        )


class DockerSandboxRunner:
    def __init__(self, settings: Settings, image: str = SANDBOX_IMAGE):
        import docker  # lazy import

        self._settings = settings
        self._image = image
        self._client = docker.from_env()
        self._client.ping()

    def run_coverage(self, repo_root: Path) -> SandboxResult:
        repo_root = repo_root.resolve()
        if not has_discoverable_tests(repo_root):
            return SandboxResult(
                status=SandboxStatus.NO_RUNNER, backend="docker",
                error="no discoverable test runner (tests/ or test_*.py)",
            )

        s = self._settings
        with tempfile.TemporaryDirectory(prefix="reposage-scratch-") as scratch:
            container = None
            try:
                container = self._client.containers.run(
                    self._image,
                    detach=True,
                    # --- ISOLATION (Req 6): single source of truth ---
                    **isolation_run_kwargs(s),
                    environment={
                        "REPO_DIR": "/work/repo",
                        "SCRATCH": "/scratch",
                        "TIMEOUT_SECONDS": str(s.sandbox_timeout_seconds),
                    },
                    volumes={
                        str(repo_root): {"bind": "/work/repo", "mode": "ro"},
                        scratch: {"bind": "/scratch", "mode": "rw"},
                    },
                )
                try:
                    result = container.wait(timeout=s.sandbox_timeout_seconds + 30)
                    exit_code = result.get("StatusCode", None)
                    timed_out = False
                except Exception as exc:  # read timeout -> kill
                    logger.warning("Sandbox wait failed/timeout: %s", exc)
                    exit_code = None
                    timed_out = True
                    try:
                        container.kill()
                    except Exception:
                        pass

                logs = ""
                try:
                    logs = container.logs().decode("utf-8", errors="replace")
                except Exception:
                    pass

                return self._collect(scratch, exit_code, timed_out, logs, "docker")
            except Exception as exc:
                logger.exception("Docker sandbox error: %s", exc)
                return SandboxResult(
                    status=SandboxStatus.ERROR, backend="docker", error=str(exc)
                )
            finally:
                if container is not None:
                    try:
                        container.remove(force=True)  # always destroy (Req 6)
                    except Exception:
                        pass

    def _collect(self, scratch, exit_code, timed_out, logs, backend) -> SandboxResult:
        scratch_p = Path(scratch)
        stdout = _read(scratch_p / "stdout.txt")
        stderr = _read(scratch_p / "stderr.txt") + logs
        duration = None
        result_json = scratch_p / "result.json"
        if result_json.exists():
            try:
                meta = json.loads(result_json.read_text(encoding="utf-8"))
                duration = meta.get("duration_seconds")
                if exit_code is None:
                    exit_code = meta.get("exit_code")
            except Exception:
                pass

        cov_by_module: dict[str, float] = {}
        total = None
        cov_file = scratch_p / "coverage.json"
        cov_available = False
        if cov_file.exists():
            try:
                cov_by_module, total = parse_coverage_file(str(cov_file))
                cov_available = True
            except Exception as exc:
                logger.warning("coverage parse failed: %s", exc)

        status = SandboxStatus.TIMEOUT if timed_out else SandboxStatus.COMPLETED
        return SandboxResult(
            status=status, exit_code=exit_code, duration_seconds=duration,
            stdout=stdout, stderr=stderr, coverage_available=cov_available,
            coverage_by_file=cov_by_module, total_coverage=total, backend=backend,
        )


class LocalSubprocessRunner:
    """DEV ONLY. Runs pytest on the host. Refuses unless explicitly allowed."""

    def __init__(self, settings: Settings, allow: bool = False):
        self._settings = settings
        self._allow = allow

    def run_coverage(self, repo_root: Path) -> SandboxResult:
        if not self._allow:
            return SandboxResult(
                status=SandboxStatus.UNAVAILABLE, backend="none",
                error="local runner disabled; refusing to run untrusted code "
                      "outside a sandbox (Req 6).",
            )
        repo_root = repo_root.resolve()
        if not has_discoverable_tests(repo_root):
            return SandboxResult(
                status=SandboxStatus.NO_RUNNER, backend="local",
                error="no discoverable test runner",
            )
        with tempfile.TemporaryDirectory(prefix="reposage-cov-") as scratch:
            cov_json = Path(scratch) / "coverage.json"
            cmd = [
                sys.executable, "-m", "pytest",
                f"--cov={repo_root}",
                f"--cov-report=json:{cov_json}",
                "-q",
            ]
            try:
                proc = subprocess.run(
                    cmd, cwd=str(repo_root), capture_output=True, text=True,
                    timeout=self._settings.sandbox_timeout_seconds,
                )
                status = SandboxStatus.COMPLETED
                exit_code = proc.returncode
                stdout, stderr = proc.stdout, proc.stderr
            except subprocess.TimeoutExpired as exc:
                return SandboxResult(
                    status=SandboxStatus.TIMEOUT, backend="local",
                    error=str(exc), stdout=(exc.stdout or ""), stderr=(exc.stderr or ""),
                )
            cov_by_module: dict[str, float] = {}
            total = None
            cov_available = False
            if cov_json.exists():
                try:
                    cov_by_module, total = parse_coverage_file(str(cov_json))
                    cov_available = True
                except Exception:
                    pass
            return SandboxResult(
                status=status, exit_code=exit_code, duration_seconds=None,
                stdout=stdout, stderr=stderr, coverage_available=cov_available,
                coverage_by_file=cov_by_module, total_coverage=total, backend="local",
            )


def get_sandbox_runner(settings: Settings) -> SandboxRunner:
    """Return the safest available runner.

    Prefers Docker. If Docker is unavailable, returns an UnavailableSandboxRunner
    (NOT the local runner) so untrusted code is never executed unsandboxed by
    default (task 5.8).
    """
    try:
        return DockerSandboxRunner(settings)
    except Exception as exc:
        logger.warning("Docker sandbox unavailable (%s); coverage will be reported "
                       "as unavailable.", exc)
        return UnavailableSandboxRunner(f"Docker unavailable: {exc}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""