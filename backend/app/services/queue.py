"""Job queue abstraction (task 9.4).

Two backends behind one interface:

* ``RedisRQQueue`` (production): enqueues analysis jobs onto Redis via RQ; a
  separate worker process (app/worker.py) executes them.
* ``SynchronousQueue`` (dev/tests): runs the job in-process immediately.

``get_job_queue`` returns the Redis queue when Redis is reachable, else the
synchronous queue. This keeps the API functional without Redis/Docker while
preserving the async contract in production.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@runtime_checkable
class JobQueue(Protocol):
    def enqueue_analysis(self, run_id: str) -> None: ...


def _run_analysis_job(run_id: str) -> None:
    """Module-level entrypoint so RQ can import + call it by dotted path."""
    from app.config import get_settings
    from app.db.session import session_scope
    from app.services.executor import execute_analysis

    with session_scope() as session:
        execute_analysis(run_id, session, get_settings())


class SynchronousQueue:
    """Executes the job immediately, in-process (dev/tests)."""

    def enqueue_analysis(self, run_id: str) -> None:
        logger.info("SynchronousQueue: executing run %s inline", run_id)
        _run_analysis_job(run_id)


class RedisRQQueue:
    def __init__(self, redis_url: str, queue_name: str = "reposage"):
        import redis  # lazy
        from rq import Queue

        self._conn = redis.Redis.from_url(redis_url)
        self._conn.ping()
        self._queue = Queue(queue_name, connection=self._conn)

    def enqueue_analysis(self, run_id: str) -> None:
        self._queue.enqueue(
            "app.services.queue._run_analysis_job", run_id, job_timeout="30m"
        )


def get_job_queue(settings: Settings | None = None) -> JobQueue:
    settings = settings or get_settings()
    try:
        return RedisRQQueue(settings.redis_url)
    except Exception as exc:
        logger.warning("Redis/RQ unavailable (%s); using synchronous in-process "
                       "queue.", exc)
        return SynchronousQueue()