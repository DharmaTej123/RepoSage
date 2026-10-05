"""Ingestion service tests (tasks 0.3 / 0.4, Req 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.services.ingestion import (
    IngestionService,
    UnsupportedRepositoryError,
)


def test_ingest_local_python_repo(tmp_env, sample_python_repo: Path):
    settings = get_settings()
    svc = IngestionService(settings)
    result = svc.ingest("run-1", repo_path=str(sample_python_repo))

    assert result.language == "python"
    assert "requirements.txt" in result.manifest_files
    assert len(result.revision) == 40  # git sha
    assert result.workdir.exists()
    assert (result.workdir / "app.py").exists()
    assert result.size_mb >= 0


def test_size_limit_rejects(tmp_env, sample_python_repo: Path, monkeypatch):
    monkeypatch.setenv("REPOSAGE_MAX_REPO_SIZE_MB", "0.0000001")
    get_settings.cache_clear()
    settings = get_settings()
    svc = IngestionService(settings)
    with pytest.raises(Exception) as exc:
        svc.ingest("run-2", repo_path=str(sample_python_repo))
    assert "exceeds limit" in str(exc.value)


def test_non_python_repo_rejected(tmp_env, tmp_path: Path):
    from git import Actor, Repo

    repo_dir = tmp_path / "js_repo"
    repo_dir.mkdir()
    (repo_dir / "index.js").write_text("console.log('hi')\n", encoding="utf-8")
    (repo_dir / "package.json").write_text('{"name":"x"}\n', encoding="utf-8")
    repo = Repo.init(repo_dir)
    repo.index.add(["index.js", "package.json"])
    author = Actor("Dev", "dev@example.com")
    repo.index.commit("init", author=author, committer=author)

    settings = get_settings()
    svc = IngestionService(settings)
    with pytest.raises(UnsupportedRepositoryError):
        svc.ingest("run-3", repo_path=str(repo_dir))


def test_non_git_path_rejected(tmp_env, tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("x = 1\n", encoding="utf-8")
    settings = get_settings()
    svc = IngestionService(settings)
    with pytest.raises(Exception) as exc:
        svc.ingest("run-4", repo_path=str(plain))
    assert "not a git repository" in str(exc.value)
