"""Shared pytest fixtures.

Tests run against an on-disk SQLite database and a temporary workdir so no
external infrastructure (Postgres/Neo4j/Redis/Docker) is required for Phase 0.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Configure settings BEFORE any app module reads them.
os.environ.setdefault("REPOSAGE_ENVIRONMENT", "test")


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a temp SQLite DB + temp workdir and reset caches."""
    db_path = tmp_path / "test.db"
    workdir = tmp_path / "workdir"
    monkeypatch.setenv("REPOSAGE_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("REPOSAGE_WORKDIR_ROOT", str(workdir))

    from app.config import get_settings
    from app.db import session as db_session

    get_settings.cache_clear()
    db_session.reset_engine_for_tests()
    db_session.init_db()

    yield

    db_session.reset_engine_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def sample_python_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo containing Python sources + a manifest."""
    from git import Actor, Repo

    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()
    (repo_dir / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    (repo_dir / "app.py").write_text(
        "import utils\n\n\ndef main():\n    return utils.greet()\n", encoding="utf-8"
    )
    (repo_dir / "utils.py").write_text(
        "def greet():\n    return 'hi'\n", encoding="utf-8"
    )

    repo = Repo.init(repo_dir)
    repo.index.add(["requirements.txt", "app.py", "utils.py"])
    author = Actor("Test Dev", "dev@example.com")
    repo.index.commit("initial commit", author=author, committer=author)
    return repo_dir
