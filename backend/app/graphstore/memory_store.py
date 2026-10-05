"""In-memory graph store — used in tests and as a fallback when Neo4j is
unreachable. Backed by the NetworkX ModuleGraph so queries match the Neo4j
semantics exactly.
"""

from __future__ import annotations

from app.analyzers.graph import ModuleGraph
from app.analyzers.models import ArchitectureGraph, ModuleCentrality


class InMemoryGraphStore:
    def __init__(self) -> None:
        # keyed by (repo_id, revision)
        self._archs: dict[tuple[str, str], ArchitectureGraph] = {}
        self._graphs: dict[tuple[str, str], ModuleGraph] = {}

    def persist_architecture(self, repo_id: str, arch: ArchitectureGraph) -> None:
        key = (repo_id, arch.revision)
        self._archs[key] = arch
        self._graphs[key] = ModuleGraph.from_architecture(arch)

    def _graph(self, repo_id: str, revision: str) -> ModuleGraph | None:
        return self._graphs.get((repo_id, revision))

    def direct_dependencies(self, repo_id: str, revision: str, module: str) -> list[str]:
        g = self._graph(repo_id, revision)
        return g.direct_dependencies(module) if g else []

    def transitive_dependencies(self, repo_id: str, revision: str, module: str) -> list[str]:
        g = self._graph(repo_id, revision)
        return g.transitive_dependencies(module) if g else []

    def blast_radius(self, repo_id: str, revision: str, module: str) -> list[str]:
        g = self._graph(repo_id, revision)
        return g.blast_radius(module) if g else []

    def high_centrality_modules(
        self, repo_id: str, revision: str, top_n: int = 10
    ) -> list[ModuleCentrality]:
        arch = self._archs.get((repo_id, revision))
        g = self._graph(repo_id, revision)
        if not arch or not g:
            return []
        return g.high_centrality_modules(arch.centrality, top_n=top_n)

    def close(self) -> None:  # no-op
        pass
