"""Run + results + graph + findings + query endpoints (Req 1, 11, 12; Phase 9).

Endpoints:
* POST /runs                       - submit a repository (enqueues analysis)
* GET  /runs/{job_id}/status       - job + per-agent status
* GET  /runs/{job_id}/results      - findings + artifacts + analysis completeness
* GET  /runs/{job_id}/graph        - architecture graph nodes/edges
* GET  /runs/{job_id}/findings/{finding_id} - single finding + evidence
* POST /runs/{job_id}/query        - interactive copilot question
* GET  /repos/{repo_id}/history    - prior runs for a repo
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, settings_dependency
from app.config import Settings
from app.db.models import Evidence as EvidenceRow
from app.db.models import Finding as FindingRow
from app.db.models import Job, Repository, Run
from app.schemas.results import (
    AnalysisStatusOut,
    EvidenceOut,
    FindingOut,
    GraphEdgeOut,
    GraphNodeOut,
    HistoryEntry,
    QueryRequest,
    QueryResponse,
    RepoHistoryResponse,
    RunGraphResponse,
    RunResultsResponse,
    SourceRefOut,
)
from app.schemas.run import (
    JobStatus,
    RepositoryMetadata,
    RunStatusResponse,
    SubmitRunRequest,
    SubmitRunResponse,
)
from app.services.runs import submit_run

router = APIRouter(prefix="/runs", tags=["runs"])
repos_router = APIRouter(prefix="/repos", tags=["repos"])

INCOMPLETE_STATES = {"pending", "running", "skipped", "not_applicable"}


def _job_or_404(session: Session, job_id: str) -> tuple[Job, Run]:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    run = session.get(Run, job.run_id)
    assert run is not None
    return job, run


def _analysis_status(job: Job) -> AnalysisStatusOut:
    ns = job.agent_status or {}
    return AnalysisStatusOut(
        node_status=ns,
        incomplete=[k for k, v in ns.items() if v in INCOMPLETE_STATES],
        failed=[k for k, v in ns.items() if v == "failed"],
        skipped=[k for k, v in ns.items() if v in ("skipped", "not_applicable")],
    )


@router.post("", response_model=SubmitRunResponse, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    payload: SubmitRunRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(settings_dependency),
) -> SubmitRunResponse:
    job = submit_run(
        session, settings,
        repo_url=payload.repo_url, repo_path=payload.repo_path,
        objective=payload.objective,
    )
    session.commit()
    run = session.get(Run, job.run_id)
    assert run is not None
    return SubmitRunResponse(
        job_id=job.id, run_id=run.id, repo_id=run.repo_id,
        status=JobStatus(job.status),
    )


@router.get("/{job_id}/status", response_model=RunStatusResponse)
def get_run_status(job_id: str, session: Session = Depends(db_session)) -> RunStatusResponse:
    job, run = _job_or_404(session, job_id)
    repository = None
    if run.revision is not None:
        repository = RepositoryMetadata(
            revision=run.revision, size_mb=run.size_mb or 0.0,
            language=run.repository.language or "unknown",
            manifest_files=run.manifest_files or [], ingested_at=run.created_at,
        )
    return RunStatusResponse(
        job_id=job.id, run_id=run.id, repo_id=run.repo_id,
        status=JobStatus(job.status), revision=run.revision, error=job.error,
        repository=repository, agent_status=job.agent_status or {},
    )


@router.get("/{job_id}/results", response_model=RunResultsResponse)
def get_run_results(job_id: str, session: Session = Depends(db_session)) -> RunResultsResponse:
    job, run = _job_or_404(session, job_id)
    finding_rows = session.scalars(
        select(FindingRow).where(FindingRow.run_id == run.id)
    ).all()
    findings_out = [_finding_to_out(session, f) for f in finding_rows]
    return RunResultsResponse(
        run_id=run.id, repo_id=run.repo_id, status=JobStatus(job.status),
        revision=run.revision, findings=findings_out,
        artifacts=run.artifacts or {}, analysis=_analysis_status(job),
    )


@router.get("/{job_id}/graph", response_model=RunGraphResponse)
def get_run_graph(job_id: str, session: Session = Depends(db_session)) -> RunGraphResponse:
    _job, run = _job_or_404(session, job_id)
    art = run.artifacts or {}
    graph = art.get("architecture_graph")
    if not graph:
        # Architecture graph is not stored verbatim in artifacts by default;
        # expose availability explicitly rather than fabricating (task 9.5).
        return RunGraphResponse(
            run_id=run.id, revision=run.revision, nodes=[], edges=[],
            available=False,
            note="Architecture graph available via the graph store; not "
                 "embedded in run artifacts.",
        )
    nodes = [GraphNodeOut(**n) for n in graph.get("nodes", [])]
    edges = [GraphEdgeOut(**e) for e in graph.get("edges", [])]
    return RunGraphResponse(run_id=run.id, revision=run.revision, nodes=nodes, edges=edges)


@router.get("/{job_id}/findings/{finding_id}", response_model=FindingOut)
def get_finding(job_id: str, finding_id: str, session: Session = Depends(db_session)) -> FindingOut:
    _job, run = _job_or_404(session, job_id)
    f = session.get(FindingRow, finding_id)
    if f is None or f.run_id != run.id:
        raise HTTPException(status_code=404, detail="Finding not found")
    return _finding_to_out(session, f)


@router.post("/{job_id}/query", response_model=QueryResponse)
def query_run(
    job_id: str, payload: QueryRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(settings_dependency),
) -> QueryResponse:
    from app.services.copilot_service import answer_question

    _job, run = _job_or_404(session, job_id)
    if run.workdir is None or run.revision is None:
        raise HTTPException(status_code=409, detail="Run not analyzed yet")
    ans = answer_question(run, payload.question, settings)
    return QueryResponse(
        question=payload.question, answer=ans.text, intent=ans.intent,
        has_evidence=ans.has_evidence, insufficient_evidence=ans.insufficient_evidence,
        sources=[SourceRefOut(source_type=s.source_type, source=s.source,
                              location=s.location) for s in ans.sources],
    )


@repos_router.get("/{repo_id}/history", response_model=RepoHistoryResponse)
def repo_history(repo_id: str, session: Session = Depends(db_session)) -> RepoHistoryResponse:
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    runs = session.scalars(
        select(Run).where(Run.repo_id == repo_id).order_by(Run.created_at.desc())
    ).all()
    entries = []
    for r in runs:
        st = r.job.status if r.job else JobStatus.PENDING.value
        entries.append(HistoryEntry(
            run_id=r.id, revision=r.revision, status=JobStatus(st),
            created_at=r.created_at.isoformat(),
        ))
    return RepoHistoryResponse(repo_id=repo_id, runs=entries)


def _finding_to_out(session: Session, f: FindingRow) -> FindingOut:
    ev_rows = session.scalars(
        select(EvidenceRow).where(EvidenceRow.finding_id == f.id)
    ).all()
    return FindingOut(
        id=f.id, agent=f.agent, category=f.category, title=f.title,
        severity=f.severity, confidence=f.confidence, description=f.description,
        affected_components=f.affected_components or [],
        recommendation=f.recommendation,
        deterministic_signals=f.deterministic_signals or {}, status=f.status,
        evidence=[EvidenceOut(
            source_type=e.source_type, source=e.source, location=e.location,
            excerpt=e.excerpt, metadata=e.evidence_metadata or {},
        ) for e in ev_rows],
    )