"""Run/job persistence orchestration built on top of ingestion.

Ingestion runs synchronously inside the request (fast). Analysis is enqueued to
the job queue (Redis/RQ in production, in-process synchronous fallback in dev/
tests). Idempotency is revision-aware (task 9.6): resubmitting the same repo at
the same HEAD revision returns the existing completed run instead of re-running.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Job, Repository, Run
from app.schemas.run import JobStatus
from app.services.ingestion import IngestionError, IngestionService
from app.services.queue import JobQueue, get_job_queue


def _normalize_source(repo_url: str | None, repo_path: str | None) -> tuple[str, str]:
    if repo_url:
        return repo_url.strip(), "url"
    assert repo_path is not None
    return repo_path.strip(), "path"


def get_or_create_repository(
    session: Session, source: str, source_type: str
) -> Repository:
    """Idempotent repository lookup by normalized source (Req 12)."""
    existing = session.scalar(select(Repository).where(Repository.source == source))
    if existing:
        return existing
    repo = Repository(source=source, source_type=source_type)
    session.add(repo)
    session.flush()
    return repo


def _existing_completed_run(session: Session, repo_id: str, revision: str) -> Run | None:
    """Return a prior COMPLETE run for the same repo+revision, if any (9.6)."""
    stmt = (
        select(Run)
        .join(Job, Job.run_id == Run.id)
        .where(Run.repo_id == repo_id, Run.revision == revision,
               Job.status == JobStatus.COMPLETE.value)
        .order_by(Run.created_at.desc())
    )
    return session.scalars(stmt).first()


def submit_run(
    session: Session,
    settings: Settings,
    *,
    repo_url: str | None,
    repo_path: str | None,
    objective: str | None = None,
    queue: JobQueue | None = None,
    force: bool = False,
) -> Job:
    """Create repo/run/job records, ingest, and enqueue analysis.

    On ingestion failure the job is marked ``failed`` (caller still gets a job
    id). If a completed run for the same repo+revision exists and ``force`` is
    False, its job is returned unchanged (idempotency, task 9.6).
    """
    source, source_type = _normalize_source(repo_url, repo_path)
    repo = get_or_create_repository(session, source, source_type)

    run = Run(repo_id=repo.id, objective=objective)
    session.add(run)
    session.flush()

    job = Job(run_id=run.id, status=JobStatus.RUNNING.value, agent_status={})
    session.add(job)
    session.flush()

    ingestion = IngestionService(settings)
    try:
        result = ingestion.ingest(run.id, repo_url=repo_url, repo_path=repo_path)
    except IngestionError as exc:
        job.status = JobStatus.FAILED.value
        job.error = str(exc)
        session.flush()
        return job

    run.revision = result.revision
    run.size_mb = result.size_mb
    run.manifest_files = result.manifest_files
    run.workdir = str(result.workdir)
    repo.language = result.language
    session.flush()

    # Revision-aware idempotency (task 9.6).
    if not force:
        prior = _existing_completed_run(session, repo.id, result.revision)
        if prior is not None:
            job.status = JobStatus.COMPLETE.value
            job.error = None
            job.agent_status = {"idempotent": f"reused run {prior.id}"}
            session.flush()
            return job

    job.status = JobStatus.PENDING.value
    job.error = None
    session.flush()

    # Enqueue analysis (synchronous fallback executes inline in dev/tests).
    session.commit()  # persist ingested run before the worker reads it
    q = queue or get_job_queue(settings)
    q.enqueue_analysis(run.id)

    session.refresh(job)
    return job