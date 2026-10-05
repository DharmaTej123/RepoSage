"""Response schemas for results / graph / history / findings / query (Phase 9)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.run import JobStatus


class EvidenceOut(BaseModel):
    source_type: str
    source: str
    location: str | None = None
    excerpt: str | None = None
    metadata: dict = Field(default_factory=dict)


class FindingOut(BaseModel):
    id: str
    agent: str
    category: str
    title: str
    severity: str
    confidence: float
    description: str
    affected_components: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    deterministic_signals: dict = Field(default_factory=dict)
    status: str
    evidence: list[EvidenceOut] = Field(default_factory=list)


class AnalysisStatusOut(BaseModel):
    """Explicit per-analysis completeness (task 9.5)."""

    node_status: dict[str, str] = Field(default_factory=dict)
    incomplete: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class RunResultsResponse(BaseModel):
    run_id: str
    repo_id: str
    status: JobStatus
    revision: str | None = None
    findings: list[FindingOut] = Field(default_factory=list)
    artifacts: dict = Field(default_factory=dict)
    analysis: AnalysisStatusOut


class GraphNodeOut(BaseModel):
    id: str
    kind: str
    name: str
    file_path: str | None = None
    metadata: dict = Field(default_factory=dict)


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    kind: str


class RunGraphResponse(BaseModel):
    run_id: str
    revision: str | None = None
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
    available: bool = True
    note: str | None = None


class HistoryEntry(BaseModel):
    run_id: str
    revision: str | None
    status: JobStatus
    created_at: str


class RepoHistoryResponse(BaseModel):
    repo_id: str
    runs: list[HistoryEntry] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None


class SourceRefOut(BaseModel):
    source_type: str
    source: str
    location: str | None = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    intent: str
    has_evidence: bool
    insufficient_evidence: bool
    sources: list[SourceRefOut] = Field(default_factory=list)