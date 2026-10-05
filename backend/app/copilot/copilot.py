"""Copilot orchestrator (ties Phase 8 together).

Given the analysis results of a run (architecture graph, ownership report, code
chunks, repo working dir), answers interactive questions by routing to the
appropriate retriever(s) and generating an evidence-backed answer. Uses the
conversation session to resolve follow-up references ("it", "that module").
"""

from __future__ import annotations

from pathlib import Path

from app.copilot.answer import Answer, AnswerGenerator
from app.copilot.retrieval import (
    GitRetriever,
    GraphRetriever,
    Retrieved,
    SourceRetriever,
    VectorRetriever,
)
from app.copilot.router import QueryIntent, QueryRouter, RouteDecision
from app.copilot.session import ConversationSession
from app.analyzers.models import ArchitectureGraph
from app.analyzers.githistory.models import OwnershipReport
from app.synthesis.chunking import CodeChunk
from app.synthesis.embeddings import EmbeddingProvider, HashingEmbeddingProvider

_FOLLOWUP_TOKENS = ("it", "that", "this", "the module", "there")


class Copilot:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        architecture: ArchitectureGraph | None = None,
        ownership: OwnershipReport | None = None,
        chunks: list[CodeChunk] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self._router = QueryRouter()
        self._generator = AnswerGenerator()
        self._arch = architecture
        self._graph_r = GraphRetriever(architecture) if architecture else None
        self._git_r = GitRetriever(ownership) if ownership else None
        provider = embedding_provider or HashingEmbeddingProvider()
        self._vector_r = VectorRetriever(chunks or [], provider) if chunks else None
        self._source_r = SourceRetriever(repo_root, architecture) if repo_root else None
        self._known_modules = architecture.module_ids() if architecture else []

    def ask(self, question: str, session: ConversationSession | None = None) -> Answer:
        decision = self._router.route(question, self._known_modules)

        # Follow-up resolution: reuse last module if question refers back (8.8).
        if decision.target_module is None and session is not None:
            if any(tok in question.lower() for tok in _FOLLOWUP_TOKENS):
                decision.target_module = session.last_module()

        retrieved = self._retrieve(decision)
        answer = self._generator.generate(question, decision, retrieved)

        if session is not None:
            session.add(question, answer.text, decision.intent.value, decision.target_module)
        return answer

    def _retrieve(self, decision: RouteDecision) -> list[Retrieved]:
        """Retrieve for the routed intent.

        Intent-specific retrievers are NOT allowed to silently fall back to
        semantic search when their required source is unavailable: an ownership
        question with no git data must return empty so the answer generator's
        guardrail fires (task 8.9), rather than answering from unrelated code.
        """
        intent = decision.intent
        module = decision.target_module
        out: list[Retrieved] = []

        if intent == QueryIntent.DEPENDENCY:
            if self._graph_r and module:
                out += self._graph_r.dependents(module)
                out += self._graph_r.dependencies(module)
        elif intent == QueryIntent.BLAST_RADIUS:
            if self._graph_r and module:
                out += self._graph_r.blast_radius(module)
        elif intent == QueryIntent.OWNERSHIP:
            if self._git_r and module:
                out += self._git_r.contributors(module)
        elif intent == QueryIntent.READING_ORDER:
            if self._graph_r:
                out += self._graph_r.central_modules()
        elif intent == QueryIntent.RISK:
            if module and self._graph_r:
                out += self._graph_r.dependents(module)
            if module and self._vector_r:
                out += self._vector_r.search(f"risk {module}")
        elif intent == QueryIntent.FLOW:
            if self._vector_r:
                out += self._vector_r.search("request flow order processing")
            if self._graph_r:
                out += self._graph_r.central_modules(top_n=5)
        else:  # SEMANTIC
            if self._vector_r:
                out += self._vector_r.search(decision.target_module or "")
            if not out and self._source_r and module:
                out += self._source_r.get_module_source(module)

        return out