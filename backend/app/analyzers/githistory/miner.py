"""GitPython commit-log mining (tasks 3.1, 3.2).

Iterates commits on the current branch within a configurable recency window,
capturing author, timestamp, changed files, and line churn. Changed Python
files are mapped to module ids using the same convention as the AST parser so
ownership joins cleanly with the architecture graph.

All computation is deterministic; no LLM involvement.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from git import Repo

from app.analyzers.githistory.models import (
    AuthorContribution,
    CommitRecord,
    ModuleOwnership,
)

logger = logging.getLogger(__name__)


def file_to_module(rel_path: str) -> str | None:
    """Map a repo-relative path to a dotted module id, or None if not Python."""
    p = Path(rel_path)
    if p.suffix != ".py":
        return None
    if p.name == "__init__.py":
        parts = p.parent.parts
    else:
        parts = p.with_suffix("").parts
    return ".".join(parts) if parts else None


class GitHistoryMiner:
    def __init__(self, repo_root: Path, window_days: int):
        self.repo_root = Path(repo_root)
        self.window_days = window_days

    def mine(self) -> list[CommitRecord]:
        repo = Repo(self.repo_root)
        if repo.bare:
            return []
        try:
            _ = repo.head.commit
        except (ValueError, Exception):  # empty repo / no commits
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.window_days)
        records: list[CommitRecord] = []
        try:
            self._collect_commits(repo, cutoff, records)
        finally:
            repo.close()
        return records

    def _collect_commits(self, repo, cutoff, records: list[CommitRecord]) -> None:
        for commit in repo.iter_commits():
            authored = datetime.fromtimestamp(commit.authored_date, tz=timezone.utc)
            if authored < cutoff:
                # iter_commits is newest-first on a linear history; keep scanning
                # in case of out-of-order dates, but this is the common cutoff.
                continue
            stats = commit.stats
            changed = list(stats.files.keys())
            insertions = stats.total.get("insertions", 0)
            deletions = stats.total.get("deletions", 0)
            records.append(
                CommitRecord(
                    sha=commit.hexsha,
                    author_name=(commit.author.name or "unknown"),
                    author_email=(commit.author.email or "unknown"),
                    authored_at=authored,
                    changed_files=changed,
                    insertions=insertions,
                    deletions=deletions,
                )
            )

    def aggregate(
        self, commits: list[CommitRecord], bus_factor_threshold: float
    ) -> list[ModuleOwnership]:
        """Aggregate per-module churn and contribution (task 3.2 / 3.3)."""
        # module -> author_key -> [commits, churn]
        per_module: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0])
        )
        author_display: dict[str, tuple[str, str]] = {}

        for c in commits:
            author_key = c.author_email.lower()
            author_display[author_key] = (c.author_name, c.author_email)
            # Per-file churn is not exposed per file by GitStats.total, so we
            # distribute the commit's churn evenly across its changed *modules*
            # (deterministic approximation) and count 1 commit per touched module.
            modules_touched = {
                m for f in c.changed_files if (m := file_to_module(f)) is not None
            }
            if not modules_touched:
                continue
            per_module_churn = c.churn // max(len(modules_touched), 1)
            for module in modules_touched:
                per_module[module][author_key][0] += 1
                per_module[module][author_key][1] += per_module_churn

        results: list[ModuleOwnership] = []
        for module, authors in per_module.items():
            contributors = [
                AuthorContribution(
                    author_name=author_display[k][0],
                    author_email=author_display[k][1],
                    commits=v[0],
                    churn=v[1],
                )
                for k, v in authors.items()
            ]
            contributors.sort(key=lambda a: (a.commits, a.churn), reverse=True)
            total_commits = sum(a.commits for a in contributors)
            total_churn = sum(a.churn for a in contributors)
            primary = contributors[0] if contributors else None
            share = (primary.commits / total_commits) if primary and total_commits else 0.0

            results.append(
                ModuleOwnership(
                    module=module,
                    total_commits=total_commits,
                    total_churn=total_churn,
                    contributors=contributors,
                    primary_contributor=(
                        f"{primary.author_name} <{primary.author_email}>"
                        if primary else None
                    ),
                    primary_contributor_share=share,
                    bus_factor_flag=(
                        share >= bus_factor_threshold and len(contributors) > 0
                    ),
                )
            )
        results.sort(key=lambda m: m.total_churn, reverse=True)
        return results
