"""Observability: LangSmith tracing wiring (task 4.10).

LangGraph/LangChain pick up tracing from environment variables. We enable it
only when ``settings.langsmith_tracing`` is true, and we attach run/job
identifiers as run metadata so traces are searchable by ``job_id`` / ``run_id``
and per node.

Deterministic analyzer work and LLM work stay distinguishable because each node
emits its own :class:`AgentMetricRecord` with ``llm_tokens`` (0 for
deterministic nodes).
"""

from __future__ import annotations

import logging
import os

from app.config import Settings
from app.orchestration.state import RunState

logger = logging.getLogger(__name__)

_configured = False


def configure_tracing(settings: Settings) -> None:
    """Idempotently set LangSmith env vars based on settings."""
    global _configured
    if _configured:
        return
    if settings.langsmith_tracing:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)
        logger.info("LangSmith tracing enabled (project=%s).", settings.langsmith_project)
    else:
        # Explicitly disable to avoid accidental external calls in dev/tests.
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    _configured = True


def run_metadata(state: RunState) -> dict:
    """Metadata attached to the LangGraph run for trace searchability."""
    return {
        "job_id": state.get("job_id"),
        "run_id": state.get("run_id"),
        "repo_id": state.get("repo_id"),
        "revision": state.get("revision"),
        "language": state.get("language"),
    }
