"""RQ worker entrypoint (task 9.4).

Run with:  rq worker reposage --url redis://localhost:6379/0
or:        python -m app.worker

The worker executes analysis jobs enqueued by the API. Repository code is only
ever executed inside the sandbox (Req 6); the worker itself runs the
deterministic pipeline + sandbox orchestration.
"""

from __future__ import annotations

import logging

from app.config import get_settings

logging.basicConfig(level=logging.INFO)


def main() -> None:
    import redis
    from rq import Queue, Worker

    settings = get_settings()
    conn = redis.Redis.from_url(settings.redis_url)
    worker = Worker([Queue("reposage", connection=conn)], connection=conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()