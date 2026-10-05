"""Evaluation harness tests (Phase 11)."""

from __future__ import annotations

from app.evaluation.runner import EvaluationRunner


def test_evaluation_runs_and_meets_bar():
    report = EvaluationRunner().run_all()
    assert len(report.cases) == 2

    agg = report.aggregate()
    assert agg["architecture_dependency.f1"] == 1.0
    assert agg["blast_radius.f1"] == 1.0
    assert agg["ownership.accuracy"] == 1.0
    assert agg["finding_detection.f1"] == 1.0
    assert agg["qa_correctness.accuracy"] == 1.0
    assert agg["evidence_attribution.accuracy"] == 1.0
    for c in report.cases:
        assert c.hallucination_rate == 0.0


def test_baseline_vs_agentic_recorded():
    report = EvaluationRunner().run_all()
    bva = report.baseline_vs_agentic
    assert "baseline_dependency_f1_avg" in bva
    assert "agentic_dependency_f1_avg" in bva
    assert bva["agentic_dependency_f1_avg"] >= bva["baseline_dependency_f1_avg"]


def test_report_serializes():
    report = EvaluationRunner().run_all()
    js = report.model_dump_json()
    assert "cases" in js and "baseline_vs_agentic" in js