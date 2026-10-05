"""Reasoning tests (Phase 6): evidence store, risk, correlation, validation, conflict."""

from __future__ import annotations

from app.reasoning.conflict import ConflictResolver
from app.reasoning.correlation import correlate_findings
from app.reasoning.evidence_store import build_evidence_store
from app.reasoning.risk import RiskScorer
from app.reasoning.validation import EvidenceValidator
from app.schemas.finding import (
    Evidence,
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)


def _ev(src="app/x.py"):
    return Evidence(source_type=EvidenceSourceType.FILE, source=src)


def _finding(**kw):
    base = dict(
        agent="a", category="c", title="t", severity=FindingSeverity.MEDIUM,
        confidence=0.6, description="d", affected_components=["mod.x"],
        evidence=[_ev()],
    )
    base.update(kw)
    return Finding(**base)


# ------------------------- evidence store --------------------------------

def test_evidence_store_indexes():
    f1 = _finding(affected_components=["mod.x", "mod.y"])
    f2 = _finding(affected_components=["mod.x"])
    store = build_evidence_store([f1, f2])
    assert store.evidence_count(f1.id) == 1
    assert "mod.x" in store.components()
    assert store.findings_by_component["mod.x"] == {f1.id, f2.id}


# ------------------------- risk scoring ----------------------------------

def test_risk_score_is_deterministic_and_reproducible():
    findings = [
        _finding(severity=FindingSeverity.CRITICAL, confidence=0.95,
                 category="vulnerable_dependency",
                 deterministic_signals={"severity": "critical"}),
        _finding(severity=FindingSeverity.LOW, confidence=0.4),
    ]
    scorer = RiskScorer()
    a = scorer.score_all(findings)
    b = scorer.score_all(findings)
    assert [s.score for s in a] == [s.score for s in b]  # reproducible
    # critical/vuln should rank first
    assert a[0].finding.severity == "critical"
    assert a[0].score > a[1].score


def test_risk_preserves_contributing_signals_and_explanation():
    f = _finding(severity=FindingSeverity.HIGH, confidence=0.9,
                 category="coverage_gap",
                 deterministic_signals={"coverage": 0.1, "pagerank": 0.5})
    scored = RiskScorer().score_all([f])[0]
    assert "severity" in scored.contributing_signals
    assert scored.contributing_signals["coverage_gap"] > 0
    assert scored.explanation


# ------------------------- correlation -----------------------------------

def test_correlation_no_double_counting():
    # Three findings on the same module across different categories.
    f1 = _finding(category="high_centrality", severity=FindingSeverity.INFO,
                  confidence=0.9, affected_components=["mod.core"],
                  deterministic_signals={"pagerank": 1.0})
    f2 = _finding(category="coverage_gap", severity=FindingSeverity.HIGH,
                  confidence=0.85, affected_components=["mod.core"],
                  deterministic_signals={"coverage": 0.1})
    f3 = _finding(category="bus_factor", severity=FindingSeverity.MEDIUM,
                  confidence=0.8, affected_components=["mod.core"],
                  deterministic_signals={"primary_contributor_share": 0.9})
    scored = RiskScorer().score_all([f1, f2, f3])
    groups = correlate_findings(scored)
    core = next(g for g in groups if g.component == "mod.core")
    max_member = max(s.score for s in scored)
    # Group score is bounded near the max, not the sum of three.
    assert core.group_score <= 1.0
    assert core.group_score >= max_member
    assert core.group_score < max_member + 0.2
    assert len(core.categories) == 3


# ------------------------- validation ------------------------------------

def test_validation_promotes_to_validated():
    f = _finding(severity=FindingSeverity.HIGH, confidence=0.9, evidence=[_ev()])
    out, outcomes = EvidenceValidator().validate([f])
    assert out[0].status == FindingStatus.VALIDATED.value
    assert outcomes[0].new_status == "validated"


def test_validation_disputes_important_without_evidence():
    # Bypass the model validator by using an inferred->important-like case:
    # info severity but high confidence with no evidence is 'important' by
    # confidence, and allowed to have no evidence.
    f = _finding(severity=FindingSeverity.INFO, confidence=0.95, evidence=[])
    out, outcomes = EvidenceValidator().validate([f])
    assert out[0].status == FindingStatus.DISPUTED.value
    assert outcomes[0].reason


def test_validation_skips_inferred():
    f = _finding(severity=FindingSeverity.MEDIUM, confidence=0.4, evidence=[],
                 status=FindingStatus.INFERRED)
    out, outcomes = EvidenceValidator().validate([f])
    assert out[0].status == FindingStatus.INFERRED.value
    assert outcomes == []


# ------------------------- conflict --------------------------------------

def test_conflict_resolved_by_strength():
    strong = _finding(category="vulnerable_dependency", confidence=0.95,
                      evidence=[_ev(), _ev("b.py")], affected_components=["dep.x"])
    weak = _finding(category="clean_dependency", confidence=0.5,
                    evidence=[_ev()], affected_components=["dep.x"])
    res = ConflictResolver().resolve([strong, weak])
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert c.resolved is True
    assert c.winner_id == strong.id


def test_conflict_unresolved_preserved():
    a = _finding(category="high_centrality", confidence=0.8, evidence=[_ev()],
                 affected_components=["mod.z"])
    b = _finding(category="isolated_module", confidence=0.8, evidence=[_ev()],
                 affected_components=["mod.z"])
    res = ConflictResolver().resolve([a, b])
    assert len(res.conflicts) == 1
    assert res.conflicts[0].resolved is False
    # Both findings preserved, marked disputed - never dropped.
    ids = {f.id for f in res.findings}
    assert a.id in ids and b.id in ids
    disputed = {f.id for f in res.findings if f.status == FindingStatus.DISPUTED.value}
    assert {a.id, b.id} <= disputed


def test_no_conflict_when_categories_not_opposing():
    a = _finding(category="high_centrality", affected_components=["mod.q"])
    b = _finding(category="coverage_gap", affected_components=["mod.q"])
    res = ConflictResolver().resolve([a, b])
    assert res.conflicts == []