"""Evidence, risk & tech-debt reasoning (Phase 6).

Deterministic, reproducible reasoning over specialist findings:

* evidence store aggregation (6.1),
* deterministic risk signals + normalized tech-debt scoring (6.2, 6.3, 6.4),
* correlation of related findings without double-counting (6.5, 6.6),
* evidence validation with observed/inferred/validated/disputed status
  transitions (6.7, 6.8),
* conflict resolution that preserves unresolved conflicts (6.9, 6.10).

Scoring is intentionally NOT delegated to an LLM: numeric signals are computed
from deterministic inputs so results are auditable and reproducible. LLM
reasoning (later) can explain/correlate but must not invent the numbers.
"""

from app.reasoning.evidence_store import EvidenceStore, build_evidence_store
from app.reasoning.risk import RiskScorer, ScoredFinding
from app.reasoning.correlation import correlate_findings, CorrelationGroup
from app.reasoning.validation import EvidenceValidator
from app.reasoning.conflict import ConflictResolver, Conflict

__all__ = [
    "EvidenceStore",
    "build_evidence_store",
    "RiskScorer",
    "ScoredFinding",
    "correlate_findings",
    "CorrelationGroup",
    "EvidenceValidator",
    "ConflictResolver",
    "Conflict",
]