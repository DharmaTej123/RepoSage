"""SQLAlchemy ORM models — Postgres system of record (Req 7, 12, 15).

Tables:
* ``repositories`` — one row per analyzed repo (keyed by normalized source).
* ``runs``         — one row per analysis run, linked to a repo + revision.
* ``jobs``         — async job lifecycle for a run.
* ``findings``     — structured findings emitted by agents.
* ``evidence``     — provenance records attached to findings.
* ``agent_metrics``— per-agent status / timing / tool-call / retry / error.

Design note: Postgres is the system of record for run/finding *metadata*.
Neo4j holds relationships and pgvector holds embeddings (later phases); we do
not duplicate those here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base. JSON columns use the portable JSON type so the schema
    works on both Postgres and SQLite (used in tests)."""


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # Normalized source identifier (url or path) used for idempotency lookups.
    source: Mapped[str] = mapped_column(String(1024), index=True)
    source_type: Mapped[str] = mapped_column(String(16))  # "url" | "path"
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    runs: Mapped[list["Run"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), index=True)

    # Immutable per-run repository facts (Req 1).
    revision: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    manifest_files: Mapped[list | None] = mapped_column(JSON, nullable=True)
    workdir: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Generated synthesis artifacts (onboarding, tech-debt report) keyed by
    # revision. Populated by the analysis executor (Phase 7/9).
    artifacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    repository: Mapped["Repository"] = relationship(back_populates="runs")
    job: Mapped["Job"] = relationship(
        back_populates="run", uselist=False, cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    agent_metrics: Mapped[list["AgentMetric"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True, unique=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-agent coarse status snapshot for the status endpoint (Req 12).
    agent_status: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    run: Mapped["Run"] = relationship(back_populates="job")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)

    agent: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)
    affected_components: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    deterministic_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="observed", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped["Run"] = relationship(back_populates="findings")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)

    source_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    finding: Mapped["Finding"] = relationship(back_populates="evidence")


class AgentMetric(Base):
    __tablename__ = "agent_metrics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)

    agent: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # pending/running/complete/failed/skipped
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    llm_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="agent_metrics")
