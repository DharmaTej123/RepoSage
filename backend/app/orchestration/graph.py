"""LangGraph assembly + runner (tasks 4.3, 4.8, 4.11).

Topology (Phase 4 subset of the full pipeline; risk/coverage/validation/
conflict/synthesis land in later phases):

    START -> ingest -> manager -> {architecture, dependency, git_history}
          -> normalize -> END

The three specialists fan out from ``manager`` and fan in at ``normalize``.
Their append-only writes (findings/metrics) merge via reducers, so a failure in
one specialist does not lose the others' results (task 4.11).

Compiled with a checkpointer for resume support (task 4.8).
"""

from __future__ import annotations

import functools
import logging

from langgraph.graph import END, START, StateGraph

from app.config import Settings, get_settings
from app.orchestration import nodes
from app.orchestration.observability import configure_tracing, run_metadata
from app.orchestration.state import NodeStatus, RunState

logger = logging.getLogger(__name__)


def ingest_node(state: RunState) -> dict:
    # Ingestion already happened in the service layer; this node records that
    # the run has entered the graph and validates required inputs are present.
    missing = [k for k in ("workdir", "revision") if not state.get(k)]
    if missing:
        return {
            "node_status": {"ingest": NodeStatus.FAILED.value},
            "errors": [{"agent": "ingest", "error": f"missing inputs: {missing}"}],
        }
    return {"node_status": {"ingest": NodeStatus.COMPLETE.value}}


def build_graph(settings: Settings | None = None, checkpointer=None):
    """Build and compile the workflow graph.

    ``checkpointer`` enables resume; pass a MemorySaver/SqliteSaver. When None,
    the graph compiles without checkpointing.
    """
    settings = settings or get_settings()

    arch = functools.partial(nodes.architecture_node, settings=settings)
    dep = functools.partial(nodes.dependency_node, settings=settings)
    gh = functools.partial(nodes.git_history_node, settings=settings)
    cov = functools.partial(nodes.coverage_node, settings=settings)

    builder = StateGraph(RunState)
    builder.add_node("ingest", ingest_node)
    builder.add_node("manager", nodes.manager_node)
    builder.add_node("architecture", arch)
    builder.add_node("dependency", dep)
    builder.add_node("git_history", gh)
    builder.add_node("coverage", cov)
    builder.add_node("normalize", nodes.normalize_node)
    builder.add_node("reason", nodes.reason_node)
    builder.add_node("synthesis", nodes.synthesis_node)

    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "manager")
    # Fan-out: manager -> all three specialists (they self-skip if disabled).
    builder.add_edge("manager", "architecture")
    builder.add_edge("manager", "dependency")
    builder.add_edge("manager", "git_history")
    # Coverage runs after the specialists so architecture centrality is in
    # state for the coverage x centrality cross-reference (task 5.4).
    builder.add_edge("architecture", "coverage")
    builder.add_edge("dependency", "coverage")
    builder.add_edge("git_history", "coverage")
    # Fan-in: normalize waits for coverage.
    builder.add_edge("coverage", "normalize")
    # Reasoning (validation/conflict/scoring/correlation) after normalization.
    builder.add_edge("normalize", "reason")
    # Synthesis assembles onboarding + tech-debt artifacts.
    builder.add_edge("reason", "synthesis")
    builder.add_edge("synthesis", END)

    return builder.compile(checkpointer=checkpointer)


def run_workflow(
    initial_state: RunState,
    settings: Settings | None = None,
    checkpointer=None,
    thread_id: str | None = None,
) -> RunState:
    """Execute the workflow to completion and return the final state."""
    settings = settings or get_settings()
    configure_tracing(settings)
    graph = build_graph(settings, checkpointer=checkpointer)

    config = {
        "configurable": {"thread_id": thread_id or initial_state["run_id"]},
        "metadata": run_metadata(initial_state),
        "run_name": f"reposage-run-{initial_state['run_id']}",
    }
    final_state = graph.invoke(initial_state, config=config)
    return final_state
