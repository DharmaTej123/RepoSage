"""Query router (task 8.2).

Classifies a question into an intent and selects retrieval source(s). This is
deterministic keyword/pattern routing, NOT always-vector-RAG: dependency and
blast-radius questions go to the graph, ownership questions go to git history,
"what should I read first" goes to the architecture/onboarding artifacts, and
open-ended "how/why/explain" questions use semantic vector retrieval (with
graph/source support).

A module name mentioned in the question is extracted so retrievers can target
it precisely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class QueryIntent(str, Enum):
    DEPENDENCY = "dependency"          # what depends on X / what does X depend on
    BLAST_RADIUS = "blast_radius"      # impact/blast radius of changing X
    OWNERSHIP = "ownership"            # who worked on X
    RISK = "risk"                      # why is X high risk
    READING_ORDER = "reading_order"    # what should I read first
    FLOW = "flow"                      # how does a request flow through the system
    SEMANTIC = "semantic"              # open-ended / fallback


# source labels
SRC_GRAPH = "graph"
SRC_VECTOR = "vector"
SRC_GIT = "git"
SRC_SOURCE = "source"


@dataclass
class RouteDecision:
    intent: QueryIntent
    sources: list[str] = field(default_factory=list)
    target_module: str | None = None


_MODULE_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\b")
_CAMEL_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:Service|Manager|Handler|Controller|Repository|Engine))\b")


class QueryRouter:
    def route(self, question: str, known_modules: list[str] | None = None) -> RouteDecision:
        q = question.lower()
        target = self._extract_module(question, known_modules or [])

        if any(k in q for k in ("blast radius", "impact of changing", "affected by changing",
                                 "what breaks", "ripple")):
            return RouteDecision(QueryIntent.BLAST_RADIUS, [SRC_GRAPH], target)

        if any(k in q for k in ("depend", "imports", "uses", "used by", "consumers of")):
            return RouteDecision(QueryIntent.DEPENDENCY, [SRC_GRAPH], target)

        if any(k in q for k in ("who ", "author", "worked on", "contributor", "owns", "maintain")):
            return RouteDecision(QueryIntent.OWNERSHIP, [SRC_GIT], target)

        if any(k in q for k in ("why is", "high risk", "risky", "risk area", "tech debt", "technical debt")):
            return RouteDecision(QueryIntent.RISK, [SRC_GRAPH, SRC_VECTOR], target)

        if any(k in q for k in ("read first", "where do i start", "start reading", "onboarding",
                                 "get started", "reading order")):
            return RouteDecision(QueryIntent.READING_ORDER, [SRC_GRAPH], target)

        if any(k in q for k in ("flow through", "request flow", "how does", "data flow",
                                 "end to end", "end-to-end")):
            return RouteDecision(QueryIntent.FLOW, [SRC_VECTOR, SRC_GRAPH, SRC_SOURCE], target)

        return RouteDecision(QueryIntent.SEMANTIC, [SRC_VECTOR, SRC_SOURCE], target)

    @staticmethod
    def _extract_module(question: str, known_modules: list[str]) -> str | None:
        known = set(known_modules)
        # 1) Prefer a dotted token explicitly present in the question; if it is
        #    a known module, use it, otherwise still return it (the retriever
        #    will find nothing -> guardrail fires for unknown modules).
        m = _MODULE_RE.search(question)
        if m:
            return m.group(1)
        # 2) Exact whole-token known-module match (boundary-aware) so a short
        #    module name does not match inside a longer dotted path.
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", question))
        for mod in sorted(known, key=len, reverse=True):
            if mod in tokens:
                return mod
        # CamelCase service-like name -> match against known modules by suffix.
        c = _CAMEL_RE.search(question)
        if c:
            # Normalize by stripping underscores so CamelCase "PaymentService"
            # matches module suffix "payment_service".
            name = c.group(1).lower().replace("_", "")
            for mod in known_modules:
                if mod.split(".")[-1].lower().replace("_", "") == name:
                    return mod
            return c.group(1)
        return None