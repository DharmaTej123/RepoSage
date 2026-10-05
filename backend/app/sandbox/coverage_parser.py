"""coverage.py JSON report parsing (task 5.3 / 5.6).

Maps coverage.json (produced by `coverage json` / `pytest --cov-report=json`)
into per-file line-coverage fractions and a total. File paths are normalized to
repo-relative POSIX and mapped to dotted module ids so coverage joins with the
architecture graph (task 5.4).
"""

from __future__ import annotations

import json
from pathlib import Path


def module_id_for(rel_path: str) -> str | None:
    p = Path(rel_path)
    if p.suffix != ".py":
        return None
    if p.name == "__init__.py":
        parts = p.parent.parts
    else:
        parts = p.with_suffix("").parts
    return ".".join(parts) if parts else None


def parse_coverage_json(data: dict, repo_root: str | None = None) -> tuple[dict[str, float], float | None]:
    """Return (coverage_by_module, total_fraction).

    coverage.json shape:
      {"files": {"path.py": {"summary": {"percent_covered": 87.5, ...}}},
       "totals": {"percent_covered": 90.0}}
    """
    files = data.get("files", {}) or {}
    by_module: dict[str, float] = {}
    root = Path(repo_root).resolve() if repo_root else None

    for raw_path, entry in files.items():
        rel = raw_path
        if root:
            try:
                rel = Path(raw_path).resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                rel = Path(raw_path).as_posix()
        else:
            rel = Path(raw_path).as_posix()
        module = module_id_for(rel)
        if module is None:
            continue
        summary = entry.get("summary", {}) or {}
        pct = summary.get("percent_covered")
        if pct is None:
            continue
        by_module[module] = round(float(pct) / 100.0, 4)

    totals = data.get("totals", {}) or {}
    total_pct = totals.get("percent_covered")
    total = round(float(total_pct) / 100.0, 4) if total_pct is not None else None
    return by_module, total


def parse_coverage_file(path: str, repo_root: str | None = None) -> tuple[dict[str, float], float | None]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return parse_coverage_json(data, repo_root=repo_root)