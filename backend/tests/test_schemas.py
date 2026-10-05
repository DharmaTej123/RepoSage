"""Finding/Evidence contract tests (task 0.6, Req 7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import Evidence, EvidenceSourceType, Finding, FindingStatus


def _evidence() -> Evidence:
    return Evidence(
        source_type=EvidenceSourceType.FILE,
        source="app/payments.py",
        location="L10-L20",
    )


def test_finding_with_evidence_is_valid():
    f = Finding(
        agent="architecture",
        category="centrality",
        title="High centrality module",
        severity="high",
        confidence=0.9,
        description="Many modules import this.",
        affected_components=["app.payments"],
        evidence=[_evidence()],
        recommendation="Add tests before refactoring.",
    )
    assert f.id.startswith("finding-")
    assert f.severity == "high"
    assert f.status == "observed"


def test_high_severity_without_evidence_rejected():
    with pytest.raises(ValidationError):
        Finding(
            agent="architecture",
            category="centrality",
            title="No evidence",
            severity="high",
            confidence=0.5,
            description="Should fail: severity asserted but no evidence.",
        )


def test_inference_may_omit_evidence():
    f = Finding(
        agent="synthesis",
        category="interpretation",
        title="Likely coupling smell",
        severity="medium",
        confidence=0.4,
        description="Inferred, not yet validated.",
        status=FindingStatus.INFERRED,
    )
    assert f.status == "inferred"


def test_info_severity_without_evidence_allowed():
    f = Finding(
        agent="architecture",
        category="note",
        title="Informational",
        severity="info",
        confidence=0.2,
        description="Info-level does not assert risk.",
    )
    assert f.severity == "info"


def test_recommendation_requires_evidence():
    with pytest.raises(ValidationError):
        Finding(
            agent="architecture",
            category="note",
            title="Info with reco but no evidence",
            severity="info",
            confidence=0.2,
            description="Has a recommendation but no evidence and not inferred.",
            recommendation="Do something.",
        )


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        Finding(
            agent="a",
            category="c",
            title="t",
            severity="info",
            confidence=1.5,
            description="d",
        )
