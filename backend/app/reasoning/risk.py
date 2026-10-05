"""Deterministic risk signals + tech-debt scoring (tasks 6.2, 6.3, 6.4).

The priority score is a transparent weighted combination of normalized
deterministic signals. Every score keeps its contributing signals and a
human-readable explanation so it is fully auditable (task 6.4). No LLM is used
to compute the number.

Signals (each normalized to 0..1):
  * severity        - from the finding's own severity
  * confidence      - from the finding
  * centrality      - module PageRank (relative to max in the run)
  * churn           - recent churn (relative to max in the run)
  * coverage_gap    - 1 - coverage (only when coverage known)
  * dependency_sev  - severity of a vulnerable-dependency finding
  * bus_factor      - primary-contributor share
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.finding import Finding

# Weights sum to 1.0. Chosen to emphasize severity + centrality while still
# rewarding corroborating signals. Kept explicit for auditability.
WEIGHTS = {
    "severity": 0.35,
    "confidence": 0.10,
    "centrality": 0.20,
    "churn": 0.10,
    "coverage_gap": 0.10,
    "dependency_sev": 0.10,
    "bus_factor": 0.05,
}

_SEVERITY_SCORE = {
    "critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.25, "info": 0.05,
}


@dataclass
class ScoredFinding:
    finding: Finding
    score: float
    contributing_signals: dict[str, float] = field(default_factory=dict)
    explanation: str = ""


class RiskScorer:
    """Computes reproducible tech-debt priority scores across a finding set."""

    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = weights or WEIGHTS

    def score_all(self, findings: list[Finding]) -> list[ScoredFinding]:
        # Compute run-relative maxima for normalization (churn, centrality).
        max_pagerank = max(
            (float(f.deterministic_signals.get("pagerank", 0.0)) for f in findings),
            default=0.0,
        )
        max_churn = max(
            (float(f.deterministic_signals.get("total_churn", 0.0)) for f in findings),
            default=0.0,
        )
        scored = [self._score_one(f, max_pagerank, max_churn) for f in findings]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def _score_one(self, f: Finding, max_pr: float, max_churn: float) -> ScoredFinding:
        sig = f.deterministic_signals or {}
        signals: dict[str, float] = {}

        signals["severity"] = _SEVERITY_SCORE.get(f.severity, 0.05)
        signals["confidence"] = float(f.confidence)

        pr = float(sig.get("pagerank", 0.0))
        signals["centrality"] = (pr / max_pr) if max_pr > 0 else 0.0

        churn = float(sig.get("total_churn", 0.0))
        signals["churn"] = (churn / max_churn) if max_churn > 0 else 0.0

        if "coverage" in sig and sig["coverage"] is not None:
            signals["coverage_gap"] = max(0.0, 1.0 - float(sig["coverage"]))
        else:
            signals["coverage_gap"] = 0.0

        if f.category == "vulnerable_dependency":
            signals["dependency_sev"] = _SEVERITY_SCORE.get(
                str(sig.get("severity") or f.severity), 0.5
            )
        else:
            signals["dependency_sev"] = 0.0

        signals["bus_factor"] = float(sig.get("primary_contributor_share", 0.0))

        score = sum(self._weights[k] * signals.get(k, 0.0) for k in self._weights)
        score = round(min(1.0, score), 4)

        top = sorted(
            ((self._weights[k] * signals.get(k, 0.0), k) for k in self._weights),
            reverse=True,
        )[:3]
        explanation = "Priority driven by " + ", ".join(
            f"{name} ({signals[name]:.2f})" for _, name in top if signals[name] > 0
        ) if any(v > 0 for v in signals.values()) else "No strong risk signals."

        return ScoredFinding(
            finding=f, score=score,
            contributing_signals={k: round(v, 4) for k, v in signals.items()},
            explanation=explanation,
        )