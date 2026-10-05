"""Synthesis tests (Phase 7): chunking, embeddings, diff, synthesis."""

from __future__ import annotations

from pathlib import Path

from app.schemas.finding import (
    Evidence,
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)
from app.synthesis.agent import SynthesisAgent
from app.synthesis.chunking import chunk_repository
from app.synthesis.diff import diff_runs
from app.synthesis.embeddings import HashingEmbeddingProvider, cosine_similarity


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        '"""Core module."""\nimport os\n\n\nclass Engine:\n    def run(self):\n        return 1\n\n\ndef helper():\n    return 2\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Project\n\n" + "\n".join(f"line {i}" for i in range(100)),
        encoding="utf-8",
    )
    return root


# ------------------------- chunking --------------------------------------

def test_chunk_repository_code_and_doc(tmp_path: Path):
    root = _repo(tmp_path)
    chunks = chunk_repository(root)
    symbols = {c.symbol for c in chunks if c.kind == "code"}
    assert "Engine" in symbols
    assert "helper" in symbols
    assert any(c.symbol == "<module>" for c in chunks)
    # doc chunks exist and carry provenance
    docs = [c for c in chunks if c.kind == "doc"]
    assert docs
    assert all(c.file_path == "README.md" for c in docs)
    assert all(c.start_line >= 1 and c.end_line >= c.start_line for c in docs)


def test_chunk_provenance_line_ranges(tmp_path: Path):
    root = _repo(tmp_path)
    chunks = chunk_repository(root)
    engine = next(c for c in chunks if c.symbol == "Engine")
    assert engine.file_path == "pkg/core.py"
    assert engine.start_line < engine.end_line


# ------------------------- embeddings ------------------------------------

def test_embeddings_deterministic():
    p = HashingEmbeddingProvider()
    a = p.embed(["def run engine core"])[0]
    b = p.embed(["def run engine core"])[0]
    assert a == b
    assert len(a) == p.dimension


def test_embedding_similarity_ranks_related_text_higher():
    p = HashingEmbeddingProvider()
    query = p.embed(["payment service order processing"])[0]
    related = p.embed(["payment service handles order processing logic"])[0]
    unrelated = p.embed(["banana kangaroo telescope umbrella"])[0]
    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


# ------------------------- diff ------------------------------------------

def _f(agent="a", category="c", comps=("mod.x",), severity=FindingSeverity.MEDIUM,
       confidence=0.6):
    return Finding(
        agent=agent, category=category, title="t", severity=severity,
        confidence=confidence, description="d", affected_components=list(comps),
        evidence=[Evidence(source_type=EvidenceSourceType.FILE, source="x.py")],
    )


def test_diff_new_resolved_changed_unchanged():
    prev = [
        _f(category="vulnerable_dependency", comps=("dep.a",)),
        _f(category="coverage_gap", comps=("mod.b",), severity=FindingSeverity.HIGH),
        _f(category="bus_factor", comps=("mod.c",)),
    ]
    curr = [
        _f(category="coverage_gap", comps=("mod.b",), severity=FindingSeverity.MEDIUM),  # changed
        _f(category="bus_factor", comps=("mod.c",)),                                     # unchanged
        _f(category="high_centrality", comps=("mod.d",)),                                # new
    ]
    d = diff_runs(prev, curr)
    s = d.summary()
    assert s["new"] == 1
    assert s["resolved"] == 1     # vulnerable_dependency dep.a gone
    assert s["changed"] == 1      # coverage_gap severity changed
    assert s["unchanged"] == 1


# ------------------------- synthesis -------------------------------------

def test_synthesis_tech_debt_has_attribution():
    f = _f(category="vulnerable_dependency", comps=("dep.x",), severity=FindingSeverity.CRITICAL,
           confidence=0.95)
    state = {
        "revision": "rev1",
        "findings": [f],
        "artifacts": {"tech_debt_ranked": [
            {"finding_id": f.id, "title": f.title, "agent": f.agent,
             "category": f.category, "severity": f.severity, "status": f.status,
             "score": 0.9, "contributing_signals": {}, "explanation": "x"},
        ]},
        "node_status": {"dependency": "complete"},
        "conflicts": [],
    }
    report = SynthesisAgent().build_tech_debt_report(state)
    assert report["items"]
    item = report["items"][0]
    assert item["attribution"]  # per-finding source references present
    assert item["attribution"][0]["source_type"] == "file"


def test_synthesis_distinguishes_unavailable_from_clean():
    state = {
        "revision": "rev1",
        "findings": [],
        "artifacts": {"tech_debt_ranked": []},
        "node_status": {
            "architecture": "complete",
            "dependency": "no_finding",   # ran clean
            "git_history": "skipped",     # unavailable
            "coverage": "failed",
        },
        "conflicts": [],
    }
    report = SynthesisAgent().build_tech_debt_report(state)
    st = report["analysis_status"]
    assert st["dependency"] == "clean"
    assert st["git_history"] == "unavailable"
    assert st["coverage"] == "failed"


def test_synthesis_onboarding_labels_contributors_not_owners():
    from app.analyzers.githistory.models import ModuleOwnership, OwnershipReport

    ownership = OwnershipReport(revision="r", window_days=365, commits_analyzed=5)
    ownership.modules = [ModuleOwnership(
        module="pkg.core", total_commits=5, primary_contributor="Alice <a@x>",
        primary_contributor_share=0.8,
    )]
    state = {"revision": "r", "findings": [], "ownership_report": ownership,
             "architecture": None, "node_status": {"git_history": "complete"}}
    ob = SynthesisAgent().build_onboarding(state)
    assert ob["historical_contributors"]
    c = ob["historical_contributors"][0]
    assert "not formal ownership" in c["note"]