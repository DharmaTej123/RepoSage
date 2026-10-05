"""Node execution helpers: metrics, timing, bounded retries (tasks 4.6, 4.7).

These wrap specialist logic so every node produces a consistent
:class:`AgentMetricRecord` and so transient tool failures are retried a bounded
number of times before the node is recorded as failed (without killing the
run — task 4.11).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.orchestration.state import AgentMetricRecord, NodeStatus

logger = logging.getLogger(__name__)


class TransientToolError(Exception):
    """Marker for errors worth retrying (network, temporary I/O)."""


@dataclass
class NodeResult:
    """What a specialist body returns to the wrapper."""

    status: NodeStatus
    # Partial dict merged into state (analyzer outputs, findings, etc.).
    update: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None       # for skipped / not_applicable
    tool_calls: int = 0
    llm_tokens: int = 0


def run_node(
    agent: str,
    body: Callable[[], NodeResult],
    *,
    max_attempts: int = 3,
    retry_base_delay: float = 0.0,
) -> dict[str, Any]:
    """Execute a node body with timing, retries, and metric capture.

    Returns a state update dict containing the body's ``update`` plus
    ``agent_metrics``, ``node_status`` and (on failure) ``errors``. Never
    raises for a node failure — the run continues (task 4.11).
    """
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    attempts = 0
    last_exc: Exception | None = None
    result: NodeResult | None = None

    while attempts < max_attempts:
        attempts += 1
        try:
            result = body()
            break
        except TransientToolError as exc:
            last_exc = exc
            logger.warning("Node %s transient failure (attempt %d/%d): %s",
                           agent, attempts, max_attempts, exc)
            if retry_base_delay and attempts < max_attempts:
                time.sleep(retry_base_delay * attempts)
        except Exception as exc:  # non-transient: do not retry
            last_exc = exc
            logger.exception("Node %s failed: %s", agent, exc)
            break

    latency_ms = int((time.perf_counter() - t0) * 1000)
    ended = datetime.now(timezone.utc)

    if result is None:
        metric: AgentMetricRecord = {
            "agent": agent,
            "status": NodeStatus.FAILED.value,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "latency_ms": latency_ms,
            "tool_calls": 0,
            "retries": attempts - 1,
            "llm_tokens": 0,
            "error": str(last_exc) if last_exc else "unknown error",
            "reason": None,
        }
        return {
            "agent_metrics": [metric],
            "node_status": {agent: NodeStatus.FAILED.value},
            "errors": [{"agent": agent, "error": metric["error"]}],
        }

    metric = {
        "agent": agent,
        "status": result.status.value,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "latency_ms": latency_ms,
        "tool_calls": result.tool_calls,
        "retries": attempts - 1,
        "llm_tokens": result.llm_tokens,
        "error": None,
        "reason": result.reason,
    }
    update = dict(result.update)
    update["agent_metrics"] = [metric]
    update["node_status"] = {agent: result.status.value}
    return update
