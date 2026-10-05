"""Common Finding and Evidence contracts (Req 7).

These are the primary structured output of every specialist agent. The rules
encoded here enforce the evidence-first principle:

* Every finding carries provenance via one or more ``Evidence`` records.
* A finding that asserts a severity/recommendation must be backed by evidence
  UNLESS it is explicitly marked as an inference (``status == "inferred"``).
* Deterministic signals are kept separate from LLM interpretation.

The field set intentionally mirrors ``design.md`` section 3.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EvidenceSourceType(str, Enum):
    """Where a piece of evidence originated."""

    FILE = "file"
    LINE = "line"
    GRAPH = "graph"
    GIT = "git"
    COMMAND = "command"
    EXTERNAL_API = "external_api"


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(str, Enum):
    """Lifecycle / epistemic status of a finding.

    * ``observed``  — a deterministic fact from an analyzer.
    * ``inferred``  — an agent inference not (yet) validated against evidence.
    * ``validated`` — passed the evidence-validation stage.
    * ``disputed``  — conflicts with another finding; unresolved.
    """

    OBSERVED = "observed"
    INFERRED = "inferred"
    VALIDATED = "validated"
    DISPUTED = "disputed"


class Evidence(BaseModel):
    """A single provenance record backing a finding.

    ``source`` is the identifier of the origin (a file path, a Neo4j
    relationship id, a git commit sha, a shell command, or an external API
    endpoint). ``location`` optionally narrows it (e.g. ``L10-L42``).
    """

    source_type: EvidenceSourceType
    source: str = Field(..., min_length=1)
    location: str | None = None
    excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


class Finding(BaseModel):
    """Structured finding produced by a specialist agent."""

    id: str = Field(default_factory=lambda: f"finding-{uuid.uuid4().hex[:12]}")
    agent: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    severity: FindingSeverity
    confidence: float = Field(..., ge=0.0, le=1.0)
    description: str = Field(..., min_length=1)
    affected_components: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    recommendation: str | None = None
    # Deterministic numeric/enum signals kept distinct from LLM prose so the
    # ranking stays reproducible and auditable (Req 9).
    deterministic_signals: dict[str, Any] = Field(default_factory=dict)
    status: FindingStatus = FindingStatus.OBSERVED

    model_config = {"use_enum_values": True}

    @model_validator(mode="after")
    def _require_evidence_unless_inferred(self) -> "Finding":
        """Enforce evidence-first: a finding that carries a severity or a
        recommendation must reference evidence, unless it is explicitly an
        inference (Req 7).

        ``info`` severity is exempt because it does not assert risk.
        """
        asserts_risk = self.severity != FindingSeverity.INFO.value
        has_reco = bool(self.recommendation)
        is_inference = self.status == FindingStatus.INFERRED.value

        if (asserts_risk or has_reco) and not self.evidence and not is_inference:
            raise ValueError(
                "Finding asserting severity/recommendation must include at "
                "least one Evidence record, or be marked status='inferred'."
            )
        return self
