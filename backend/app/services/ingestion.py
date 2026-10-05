"""Repository ingestion (Req 1, tasks 0.3 / 0.4).

Responsibilities:
* Clone (URL) or copy (local path) the repository into an isolated per-run
  working directory under ``settings.workdir_root``.
* Enforce the configured size limit; reject oversized repos with a clear error.
* Detect primary language + package manifests.
* Capture the analyzed revision (HEAD sha) so all findings trace to it.
* Fail fast when the repo is not a Python repo (v1 scope).

The result is an immutable snapshot description; callers persist it to the
``runs`` table. No repository code is executed here.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, Repo

from app.config import Settings

# Manifest files we understand. Presence of a Python manifest (or *.py files)
# is what qualifies a repo for v1 analysis.
PYTHON_MANIFESTS = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile")
KNOWN_MANIFESTS = PYTHON_MANIFESTS + ("package.json",)


class IngestionError(Exception):
    """Raised when a repository cannot be ingested / is out of scope."""


class UnsupportedRepositoryError(IngestionError):
    """Repository is not a supported (Python) repository (Req 1)."""


@dataclass
class IngestionResult:
    workdir: Path
    revision: str
    size_mb: float
    language: str
    manifest_files: list[str] = field(default_factory=list)
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _dir_size_mb(path: Path) -> float:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            # Broken symlink / permission — ignore for sizing.
            continue
    return total / (1024 * 1024)


def _detect_manifests(repo_root: Path) -> list[str]:
    found: list[str] = []
    for name in KNOWN_MANIFESTS:
        if (repo_root / name).is_file():
            found.append(name)
    return found


def _has_python_sources(repo_root: Path) -> bool:
    for p in repo_root.rglob("*.py"):
        # Skip vendored / VCS dirs for the "is this a python repo" check.
        parts = set(p.parts)
        if ".git" in parts or "site-packages" in parts:
            continue
        return True
    return False


def _detect_language(repo_root: Path, manifests: list[str]) -> str:
    python_manifest = any(m in PYTHON_MANIFESTS for m in manifests)
    if python_manifest or _has_python_sources(repo_root):
        return "python"
    return "unknown"


class IngestionService:
    """Clones/copies a repository and produces an :class:`IngestionResult`."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def ingest(
        self,
        run_id: str,
        *,
        repo_url: str | None = None,
        repo_path: str | None = None,
    ) -> IngestionResult:
        if bool(repo_url) == bool(repo_path):
            raise IngestionError("Provide exactly one of repo_url or repo_path.")

        workdir = self._settings.resolved_workdir_root() / run_id
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)

        try:
            if repo_url:
                repo = self._clone(repo_url, workdir)
            else:
                repo = self._copy(Path(repo_path), workdir)  # type: ignore[arg-type]
        except (GitCommandError, InvalidGitRepositoryError) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise IngestionError(f"Failed to acquire repository: {exc}") from exc

        # --- Size limit (Req 1) ------------------------------------------
        size_mb = _dir_size_mb(workdir)
        if size_mb > self._settings.max_repo_size_mb:
            shutil.rmtree(workdir, ignore_errors=True)
            raise IngestionError(
                f"Repository size {size_mb:.1f} MB exceeds limit "
                f"{self._settings.max_repo_size_mb} MB."
            )

        # --- Revision capture (Req 1) ------------------------------------
        try:
            revision = repo.head.commit.hexsha
        except (ValueError, GitCommandError) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise IngestionError(f"Could not resolve repository HEAD: {exc}") from exc

        # --- Language / manifest detection (Req 1) -----------------------
        manifests = _detect_manifests(workdir)
        language = _detect_language(workdir, manifests)
        if language != "python":
            shutil.rmtree(workdir, ignore_errors=True)
            raise UnsupportedRepositoryError(
                "No detectable Python entry points or manifest found. "
                "RepoSage v1 supports Python repositories only."
            )

        return IngestionResult(
            workdir=workdir,
            revision=revision,
            size_mb=round(size_mb, 3),
            language=language,
            manifest_files=manifests,
        )

    def _clone(self, repo_url: str, workdir: Path) -> Repo:
        kwargs: dict = {}
        if self._settings.clone_depth:
            kwargs["depth"] = self._settings.clone_depth
        return Repo.clone_from(repo_url, workdir, **kwargs)

    def _copy(self, src: Path, workdir: Path) -> Repo:
        src = src.expanduser().resolve()
        if not src.exists() or not src.is_dir():
            raise IngestionError(f"Local repo_path does not exist: {src}")
        if not (src / ".git").exists():
            raise IngestionError(
                f"Local path is not a git repository (no .git): {src}"
            )
        # Copy into workdir/repo-name to keep an isolated immutable snapshot.
        # dirs_exist_ok because workdir was pre-created.
        shutil.copytree(src, workdir, dirs_exist_ok=True, symlinks=True)
        try:
            return Repo(workdir)
        except InvalidGitRepositoryError as exc:
            raise IngestionError(f"Copied path is not a valid git repo: {exc}") from exc
