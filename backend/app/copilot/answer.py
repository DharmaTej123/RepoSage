"""Evidence-backed answer generation (tasks 8.6, 8.7, 8.9).

Assembles a structured answer from retrieved items. Every answer carries its
source references. The guardrail: if no evidence was retrieved for a question
that requires it, the generator returns an explicit "insufficient evidence"
answer rather than fabricating one (task 8.9).

This is a deterministic template-based generator. An LLM layer can later render
the same (answer_text, sources) contract into fluent prose, but it must be
given ONLY the retrieved evidence and instructed not to add unsupported claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.copilot.retrieval import Retrieved
from app.copilot.router import QueryIntent, RouteDecision


@dataclass
class SourceRef:
    source_type: str
    source: str
    location: str | None = None


@dataclass
class Answer:
    text: str
    sources: list[SourceRef] = field(default_factory=list)
    intent: str = ""
    has_evidence: bool = True
    insufficient_evidence: bool = False


INSUFFICIENT = (
    "I don't have enough analyzed evidence to answer that reliably. "
    "The relevant analysis may not have run for this repository, or the "
    "referenced component was not found."
)


class AnswerGenerator:
    def generate(
        self, question: str, decision: RouteDecision, retrieved: list[Retrieved]
    ) -> Answer:
        if not retrieved:
            return Answer(
                text=INSUFFICIENT, sources=[], intent=decision.intent.value,
                has_evidence=False, insufficient_evidence=True,
            )

        sources = [
            SourceRef(
                source_type=r.evidence.source_type,
                source=r.evidence.source,
                location=r.evidence.location,
            )
            for r in retrieved
        ]
        text = self._render(question, decision, retrieved)
        return Answer(text=text, sources=sources, intent=decision.intent.value)

    def _render(self, question: str, decision: RouteDecision, retrieved: list[Retrieved]) -> str:
        target = decision.target_module or "the specified component"
        lines: list[str]

        if decision.intent == QueryIntent.DEPENDENCY:
            items = "\n".join(f"- {r.text}" for r in retrieved[:15])
            lines = [f"Dependency relationships for {target}:", items]
        elif decision.intent == QueryIntent.BLAST_RADIUS:
            mods = ", ".join(sorted({r.metadata.get('module', r.text) for r in retrieved})[:20])
            lines = [
                f"Approximate blast radius of changing {target}: "
                f"{len(retrieved)} module(s) transitively depend on it.",
                f"Affected: {mods}",
            ]
        elif decision.intent == QueryIntent.OWNERSHIP:
            items = "\n".join(f"- {r.text}" for r in retrieved[:10])
            lines = [
                f"Historical contributors to {target} "
                f"(historical contribution, not formal ownership):",
                items,
            ]
        elif decision.intent == QueryIntent.RISK:
            items = "\n".join(f"- {r.text}" for r in retrieved[:10])
            lines = [f"Risk-relevant signals for {target}:", items]
        elif decision.intent == QueryIntent.READING_ORDER:
            items = "\n".join(f"{i+1}. {r.text}" for i, r in enumerate(retrieved[:10]))
            lines = ["Suggested reading order (by dependency centrality):", items]
        elif decision.intent == QueryIntent.FLOW:
            items = "\n".join(f"- {r.metadata.get('file', r.text)}" for r in retrieved[:8])
            lines = ["Relevant components for that flow (semantic + graph):", items]
        else:  # SEMANTIC
            items = "\n".join(
                f"- {r.metadata.get('file','?')}: {r.text[:160].strip()}"
                for r in retrieved[:5]
            )
            lines = ["Based on the most relevant code/docs:", items]

        return "\n".join(lines)