"""Analysis executor (Phase 9).

Runs the LangGraph workflow for a run and persists results to Postgres:
findings + evidence + agent metrics + generated artifacts. Also mirrors the
architecture graph into the graph store (Neo4j or in-memory fallback).

This function is what the worker calls. It is written to be safe to run
in-process (tests / synchronous fallback) or from an RQ worker.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AgentMetric as AgentMetricRow
from app.db.models import Evidence as EvidenceRow
from app.db.models import Finding as FindingRow
from app.db.models import Job, Run
from app.graphstore.neo4j_store import get_graph_store
from app.orchestration.graph import run_workflow
from app.orchestration.state import make_initial_state
from app.schemas.finding import Finding
from app.schemas.run import JobStatus

logger = logging.getLogger(__name__)


def _persist_findings(session: Session, run_id: str, findings: list[Finding]) -> None:
    for f in findings:
        row = FindingRow(
            id=f.id, run_id=run_id, agent=f.agent, category=f.category,
            title=f.title, severity=f.severity, confidence=f.confidence,
            description=f.description, affected_components=f.affected_components,
            recommendation=f.recommendation,
            deterministic_signals=f.deterministic_signals, status=f.status,
        )
        session.add(row)
        session.flush()
        for e in f.evidence:
            session.add(EvidenceRow(
                finding_id=f.id, source_type=e.source_type, source=e.source,
                location=e.location, excerpt=e.excerpt, evidence_metadata=e.metadata,
            ))


def _persist_metrics(session: Session, run_id: str, metrics: list[dict]) -> None:
    for m in metrics:
        def _dt(v):
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except (ValueError, TypeError):
                return None
        session.add(AgentMetricRow(
            run_id=run_id, agent=m.get("agent", "?"), status=m.get("status", "?"),
            started_at=_dt(m.get("started_at")), ended_at=_dt(m.get("ended_at")),
            latency_ms=m.get("latency_ms"), tool_calls=m.get("tool_calls", 0),
            retries=m.get("retries", 0), llm_tokens=m.get("llm_tokens", 0),
            error=m.get("error"),
        ))


def execute_analysis(run_id: str, session: Session, settings: Settings | None = None) -> None:
    """Execute the pipeline for an ingested run and persist results.

    The run must already have a workdir + revision (ingestion done). Marks the
    job complete on success or failed on unexpected error; per-node skipped/
    failed states are preserved in agent_status (task 9.5).
    """
    settings = settings or get_settings()
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"run not found: {run_id}")
    job = run.job
    if run.workdir is None or run.revision is None:
        job.status = JobStatus.FAILED.value
        job.error = "run not ingested (missing workdir/revision)"
        session.flush()
        return

    job.status = JobStatus.RUNNING.value
    session.flush()

    state = make_initial_state(
        run_id=run.id, repo_id=run.repo_id, job_id=job.id,
        workdir=run.workdir, revision=run.revision,
        language=(run.repository.language or "python"),
        manifest_files=run.manifest_files or [], objective=run.objective,
    )

    try:
        final = run_workflow(state, settings=settings)
    except Exception as exc:
        logger.exception("Pipeline crashed for run %s", run_id)
        job.status = JobStatus.FAILED.value
        job.error = f"pipeline error: {exc}"
        session.flush()
        return

    findings = final.get("findings") or []
    _persist_findings(session, run.id, findings)
    _persist_metrics(session, run.id, final.get("agent_metrics") or [])

    run.artifacts = final.get("artifacts") or {}

    # Mirror architecture into the graph store (Neo4j or in-memory fallback).
    arch = final.get("architecture")
    if arch is not None:
        try:
            store = get_graph_store(settings)
            store.persist_architecture(run.repo_id, arch)
            store.close()
        except Exception as exc:
            logger.warning("Graph store persistence skipped: %s", exc)

    # Expose per-node status explicitly (task 9.5).
    job.agent_status = final.get("node_status") or {}
    # Overall status: complete if the pipeline reached synthesis, else failed.
    reached_end = job.agent_status.get("synthesis") == "complete"
    job.status = JobStatus.COMPLETE.value if reached_end else JobStatus.FAILED.value
    if not reached_end and not job.error:
        job.error = "pipeline did not reach synthesis"
    session.flush()
    logger.info("Run %s complete: %d findings", run_id, len(findings))