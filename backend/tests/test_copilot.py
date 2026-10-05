"""Copilot tests (Phase 8): router, retrieval, answers, guardrail, session."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analyzers.architecture_mapper import ArchitectureMapper
from app.analyzers.githistory.models import (
    AuthorContribution,
    ModuleOwnership,
    OwnershipReport,
)
from app.copilot import Copilot, ConversationSession
from app.copilot.answer import AnswerGenerator
from app.copilot.retrieval import GraphRetriever, VectorRetriever
from app.copilot.router import QueryIntent, QueryRouter
from app.synthesis.chunking import chunk_repository
from app.synthesis.embeddings import HashingEmbeddingProvider


@pytest.fixture
def analyzed_repo(tmp_path: Path):
    root = tmp_path / "repo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "payment_service.py").write_text(
        "from pkg import utils\n\n\nclass PaymentService:\n    def charge(self):\n        return utils.helper()\n",
        encoding="utf-8",
    )
    (pkg / "orders.py").write_text(
        "from pkg import payment_service\n\n\ndef place_order():\n    return payment_service.PaymentService().charge()\n",
        encoding="utf-8",
    )
    arch = ArchitectureMapper(root, revision="rev1").run()
    chunks = chunk_repository(root)
    ownership = OwnershipReport(revision="rev1", window_days=365, commits_analyzed=3)
    ownership.modules = [
        ModuleOwnership(
            module="pkg.payment_service", total_commits=3,
            primary_contributor="Alice <a@x>", primary_contributor_share=0.66,
            contributors=[
                AuthorContribution(author_name="Alice", author_email="a@x", commits=2),
                AuthorContribution(author_name="Bob", author_email="b@x", commits=1),
            ],
        )
    ]
    return root, arch, chunks, ownership


# ------------------------- router ----------------------------------------

def test_router_dependency_intent():
    r = QueryRouter()
    d = r.route("What depends on pkg.payment_service?", ["pkg.payment_service"])
    assert d.intent == QueryIntent.DEPENDENCY
    assert d.target_module == "pkg.payment_service"
    assert "graph" in d.sources


def test_router_blast_radius_intent():
    r = QueryRouter()
    d = r.route("What is the blast radius of changing pkg.utils?", ["pkg.utils"])
    assert d.intent == QueryIntent.BLAST_RADIUS
    assert d.sources == ["graph"]


def test_router_ownership_intent():
    r = QueryRouter()
    d = r.route("Who has worked on pkg.payment_service?", ["pkg.payment_service"])
    assert d.intent == QueryIntent.OWNERSHIP
    assert d.sources == ["git"]


def test_router_reading_order_intent():
    d = QueryRouter().route("What should I read first?")
    assert d.intent == QueryIntent.READING_ORDER


def test_router_semantic_fallback():
    d = QueryRouter().route("Explain the authentication approach")
    assert d.intent == QueryIntent.SEMANTIC
    assert "vector" in d.sources


def test_router_extracts_camelcase_service(analyzed_repo):
    _root, arch, _chunks, _own = analyzed_repo
    d = QueryRouter().route("what depends on PaymentService", arch.module_ids())
    assert d.target_module == "pkg.payment_service"


# ------------------------- retrieval -------------------------------------

def test_graph_retriever_dependents(analyzed_repo):
    _root, arch, _chunks, _own = analyzed_repo
    gr = GraphRetriever(arch)
    dependents = gr.dependents("pkg.payment_service")
    assert any("pkg.orders" in r.metadata.get("module", "") for r in dependents)
    for r in dependents:
        assert r.evidence.source_type == "graph"


def test_graph_retriever_blast_radius(analyzed_repo):
    _root, arch, _chunks, _own = analyzed_repo
    gr = GraphRetriever(arch)
    radius = {r.metadata["module"] for r in gr.blast_radius("pkg.utils")}
    assert {"pkg.payment_service", "pkg.orders"} <= radius


def test_vector_retriever_returns_evidence(analyzed_repo):
    _root, _arch, chunks, _own = analyzed_repo
    vr = VectorRetriever(chunks, HashingEmbeddingProvider())
    hits = vr.search("payment charge", top_k=3)
    assert hits
    assert all(h.evidence.source_type == "file" for h in hits)
    assert all(h.evidence.location for h in hits)


# ------------------------- guardrail -------------------------------------

def test_answer_guardrail_insufficient_evidence():
    gen = AnswerGenerator()
    from app.copilot.router import RouteDecision
    decision = RouteDecision(QueryIntent.OWNERSHIP, ["git"], "pkg.unknown")
    ans = gen.generate("who owns pkg.unknown", decision, [])
    assert ans.insufficient_evidence is True
    assert ans.has_evidence is False
    assert ans.sources == []


# ------------------------- end-to-end copilot ----------------------------

def test_copilot_dependency_answer_has_sources(analyzed_repo):
    root, arch, chunks, own = analyzed_repo
    cp = Copilot(repo_root=root, architecture=arch, ownership=own, chunks=chunks)
    ans = cp.ask("What depends on pkg.payment_service?")
    assert ans.intent == "dependency"
    assert ans.sources
    assert "pkg.orders" in ans.text


def test_copilot_ownership_says_not_owner(analyzed_repo):
    root, arch, chunks, own = analyzed_repo
    cp = Copilot(repo_root=root, architecture=arch, ownership=own, chunks=chunks)
    ans = cp.ask("Who has worked on pkg.payment_service?")
    assert "not formal ownership" in ans.text
    assert ans.sources


def test_copilot_reading_order(analyzed_repo):
    root, arch, chunks, own = analyzed_repo
    cp = Copilot(repo_root=root, architecture=arch, ownership=own, chunks=chunks)
    ans = cp.ask("What should I read first?")
    assert ans.intent == "reading_order"
    assert ans.sources


def test_copilot_followup_uses_session(analyzed_repo):
    root, arch, chunks, own = analyzed_repo
    cp = Copilot(repo_root=root, architecture=arch, ownership=own, chunks=chunks)
    session = ConversationSession(session_id="s1")
    cp.ask("What is the blast radius of changing pkg.utils?", session)
    # Follow-up without naming the module; should reuse pkg.utils.
    ans = cp.ask("who has worked on it?", session)
    assert ans.intent == "ownership"
    # pkg.utils has no ownership entry -> guardrail insufficient evidence
    assert ans.insufficient_evidence is True


def test_copilot_guardrail_when_analysis_missing(analyzed_repo):
    root, arch, chunks, _own = analyzed_repo
    # No ownership report provided -> ownership question cannot be answered.
    cp = Copilot(repo_root=root, architecture=arch, ownership=None, chunks=chunks)
    ans = cp.ask("Who has worked on pkg.payment_service?")
    assert ans.insufficient_evidence is True