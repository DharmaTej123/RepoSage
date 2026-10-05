"""Evaluation data models (ground-truth cases + results)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExpectedDependency(BaseModel):
    source: str
    target: str


class ExpectedOwnership(BaseModel):
    module: str
    primary_contributor_email: str


class ExpectedFinding(BaseModel):
    category: str
    component: str | None = None


class ExpectedQA(BaseModel):
    question: str
    # substrings that MUST appear in a correct answer
    must_include: list[str] = Field(default_factory=list)
    # whether the guardrail (insufficient evidence) is the correct response
    expect_insufficient: bool = False


class EvalCase(BaseModel):
    name: str
    # A builder key resolved to a repo path by the fixtures module.
    fixture: str
    expected_dependencies: list[ExpectedDependency] = Field(default_factory=list)
    expected_blast_radius: dict[str, list[str]] = Field(default_factory=dict)
    expected_ownership: list[ExpectedOwnership] = Field(default_factory=list)
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)
    qa: list[ExpectedQA] = Field(default_factory=list)


class MetricResult(BaseModel):
    name: str
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    accuracy: float | None = None
    detail: dict = Field(default_factory=dict)


class CaseResult(BaseModel):
    case: str
    metrics: list[MetricResult] = Field(default_factory=list)
    hallucination_rate: float | None = None


class EvalReport(BaseModel):
    generated_at: str
    cases: list[CaseResult] = Field(default_factory=list)
    baseline_vs_agentic: dict = Field(default_factory=dict)

    def aggregate(self) -> dict:
        agg: dict[str, list[float]] = {}
        for c in self.cases:
            for m in c.metrics:
                if m.f1 is not None:
                    agg.setdefault(f"{m.name}.f1", []).append(m.f1)
                if m.accuracy is not None:
                    agg.setdefault(f"{m.name}.accuracy", []).append(m.accuracy)
        return {k: round(sum(v) / len(v), 4) for k, v in agg.items() if v}


def prf(true_positive: int, false_positive: int, false_negative: int) -> MetricResult:
    p = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 1.0
    r = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 1.0
    f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
    return MetricResult(
        name="", precision=round(p, 4), recall=round(r, 4), f1=round(f1, 4),
        detail={"tp": true_positive, "fp": false_positive, "fn": false_negative},
    )