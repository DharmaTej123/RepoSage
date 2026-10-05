"""GraphStore protocol.

Both the Neo4j-backed store and the in-memory fallback implement this so the
rest of the system is agnostic to whether Neo4j is running. Neo4j is the
structural knowledge layer for actual reasoning/queries (design.md section 5),
not merely a visualization backend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.analyzers.models import ArchitectureGraph, ModuleCentrality


@runtime_checkable
class GraphStore(Protocol):
    def persist_architecture(self, repo_id: str, arch: ArchitectureGraph) -> None:
        """Persist nodes/edges/centrality for a repo revision (task 1.3)."""
        ...

    def direct_dependencies(self, repo_id: str, revision: str, module: str) -> list[str]: ...

    def transitive_dependencies(self, repo_id: str, revision: str, module: str) -> list[str]: ...

    def blast_radius(self, repo_id: str, revision: str, module: str) -> list[str]: ...

    def high_centrality_modules(
        self, repo_id: str, revision: str, top_n: int = 10
    ) -> list[ModuleCentrality]: ...

    def close(self) -> None: ...
