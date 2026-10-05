"""Evaluation harness (Phase 11).

Evaluates RepoSage against ground-truth expectations on representative Python
repositories:

* architecture relationship accuracy (11.2, 11.6),
* ownership/churn accuracy (11.3),
* dependency + coverage-risk findings (11.4),
* onboarding/copilot Q&A correctness (11.5, 11.8),
* evidence attribution accuracy (11.7),
* unsupported-claim / hallucination rate (11.9),
* a deterministic-only baseline (11.10) compared against the full agentic +
  evidence-backed pipeline (11.11),
* persisted results for regression tracking (11.12).

Ground-truth cases use small, self-contained fixture repositories so evaluation
is deterministic and offline. Real open-source repos can be added to the case
set (they clone via the ingestion service); the metric code is repo-agnostic.
"""

from app.evaluation.models import (
    EvalCase,
    EvalReport,
    MetricResult,
)
from app.evaluation.runner import EvaluationRunner

__all__ = ["EvalCase", "EvalReport", "MetricResult", "EvaluationRunner"]