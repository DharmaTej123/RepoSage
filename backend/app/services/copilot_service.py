"""Copilot service: answer a question for an analyzed run (task 9.3).

Re-derives the deterministic analysis inputs (architecture graph, ownership,
code chunks) from the run's immutable workdir snapshot and builds a Copilot to
answer the question. Re-derivation is deterministic and cheap for typical
repos; it avoids depending on a running Neo4j/pgvector for query answering while
keeping answers evidence-backed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analyzers.architecture_mapper import ArchitectureMapper
from app.analyzers.githistory.agent import GitHistoryAgent
from app.config import Settings
from app.copilot import Copilot
from app.copilot.answer import Answer
from app.db.models import Run
from app.synthesis.chunking import chunk_repository

logger = logging.getLogger(__name__)

# Small in-process cache: run_id -> Copilot (workdir snapshots are immutable).
_CACHE: dict[str, Copilot] = {}


def _build_copilot(run: Run, settings: Settings) -> Copilot:
    workdir = Path(run.workdir)
    arch = ArchitectureMapper(workdir, run.revision or "unknown").run()
    try:
        gh = GitHistoryAgent(settings)
        ownership, _commits = gh.analyze(workdir, run.revision or "unknown")
    except Exception as exc:
        logger.warning("Ownership re-derivation failed: %s", exc)
        ownership = None
    chunks = chunk_repository(workdir)
    return Copilot(
        repo_root=workdir, architecture=arch, ownership=ownership, chunks=chunks
    )


def answer_question(run: Run, question: str, settings: Settings) -> Answer:
    copilot = _CACHE.get(run.id)
    if copilot is None:
        copilot = _build_copilot(run, settings)
        _CACHE[run.id] = copilot
    return copilot.ask(question)