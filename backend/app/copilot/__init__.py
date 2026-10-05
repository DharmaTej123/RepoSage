"""Repository Knowledge & Interactive Copilot (Phase 8).

Answers questions about an analyzed repository by routing to the right
retrieval source (Neo4j graph / pgvector semantic / git history / source files),
then generating an EVIDENCE-BACKED answer with source references (Req 11).

Guardrail (task 8.9): when the required evidence is unavailable the copilot says
so instead of fabricating an answer.
"""

from app.copilot.router import QueryIntent, QueryRouter, RouteDecision
from app.copilot.retrieval import (
    Retrieved,
    GraphRetriever,
    VectorRetriever,
    GitRetriever,
    SourceRetriever,
)
from app.copilot.answer import Answer, AnswerGenerator
from app.copilot.session import ConversationSession
from app.copilot.copilot import Copilot

__all__ = [
    "QueryIntent",
    "QueryRouter",
    "RouteDecision",
    "Retrieved",
    "GraphRetriever",
    "VectorRetriever",
    "GitRetriever",
    "SourceRetriever",
    "Answer",
    "AnswerGenerator",
    "ConversationSession",
    "Copilot",
]