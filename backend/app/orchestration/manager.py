"""Manager / Investigation Agent (tasks 4.2, 4.4).

Chooses which of a BOUNDED, hardcoded set of supported analyses apply to a
repository, based on deterministic characteristics (language, manifests,
presence of tests/git history) and the optional user objective.

This is deliberately NOT an open-ended autonomous planner: the set of workflows
is fixed and enumerated. The manager only decides enable/skip + a reason, so
routing stays auditable and reproducible.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.orchestration.state import RunState

logger = logging.getLogger(__name__)

# The complete bounded set of supported specialist workflows.
SUPPORTED_WORKFLOWS = ("architecture", "dependency", "git_history", "coverage")


def _has_manifest(state: RunState) -> bool:
    manifests = state.get("manifest_files") or []
    return any(m in ("requirements.txt", "pyproject.toml") for m in manifests)


def _has_tests(workdir: str) -> bool:
    root = Path(workdir)
    if not root.exists():
        return False
    # Heuristic: a tests/ dir or any test_*.py / *_test.py file.
    if (root / "tests").is_dir():
        return True
    for p in root.rglob("test_*.py"):
        return True
    for p in root.rglob("*_test.py"):
        return True
    return False


def _has_git_history(workdir: str) -> bool:
    return (Path(workdir) / ".git").exists()


def plan_investigation(state: RunState) -> dict:
    """Return {"enabled": [...], "skipped": {name: reason}}.

    Architecture always runs for a Python repo. The others are gated on the
    availability of their inputs. The user objective can bias inclusion but
    cannot invent an unsupported workflow.
    """
    enabled: list[str] = []
    skipped: dict[str, str] = {}
    workdir = state.get("workdir", "")
    objective = (state.get("objective") or "").lower()

    # architecture
    if state.get("language") == "python":
        enabled.append("architecture")
    else:
        skipped["architecture"] = "non-Python repository (v1 supports Python only)"

    # dependency
    if _has_manifest(state):
        enabled.append("dependency")
    else:
        skipped["dependency"] = "no requirements.txt / pyproject.toml found"

    # git history
    if _has_git_history(workdir):
        enabled.append("git_history")
    else:
        skipped["git_history"] = "no .git history available"

    # coverage (Phase 5 executes it; manager only decides applicability)
    if _has_tests(workdir):
        enabled.append("coverage")
    else:
        skipped["coverage"] = "no discoverable test suite"

    # Objective-driven emphasis (does not add unsupported workflows).
    emphasis = [w for w in SUPPORTED_WORKFLOWS if w in objective and w in enabled]

    plan = {"enabled": enabled, "skipped": skipped, "emphasis": emphasis}
    logger.info("Investigation plan: %s", plan)
    return plan
