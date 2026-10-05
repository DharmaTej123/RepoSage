"""Configuration tests (task 0.5)."""

from __future__ import annotations

import pytest


def test_defaults(monkeypatch: pytest.MonkeyPatch):
    from app.config import Settings

    s = Settings()
    assert s.max_repo_size_mb == 1024
    assert s.bus_factor_threshold == 0.80
    assert s.coverage_gap_threshold == 0.50
    assert s.staleness_months == 18
    assert s.sandbox_timeout_seconds == 600


def test_env_override(monkeypatch: pytest.MonkeyPatch):
    from app.config import Settings

    monkeypatch.setenv("REPOSAGE_MAX_REPO_SIZE_MB", "50")
    monkeypatch.setenv("REPOSAGE_BUS_FACTOR_THRESHOLD", "0.6")
    s = Settings()
    assert s.max_repo_size_mb == 50
    assert s.bus_factor_threshold == 0.6


def test_workdir_root_created(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from app.config import Settings

    target = tmp_path / "wd"
    monkeypatch.setenv("REPOSAGE_WORKDIR_ROOT", str(target))
    s = Settings()
    resolved = s.resolved_workdir_root()
    assert resolved.exists()
