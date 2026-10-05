"""In-memory module dependency graph + centrality + queries.

Built on NetworkX over the IMPORTS edges. This is the deterministic query
surface used by downstream agents and by the copilot when Neo4j is not the
chosen backend. The same queries are mirrored in the Neo4j layer (task 1.7/1.8)
so the pipeline works with or without a running Neo4j.

Blast radius convention: if A imports B, then A depends on B. Changing B
affects its *dependents* (modules that import B, directly or transitively).
So blast radius of a change to module M = ancestors of M in the IMPORTS graph.
"""

from __future__ import annotations

import networkx as nx

from app.analyzers.models import (
    ArchitectureGraph,
    ModuleCentrality,
    NodeKind,
    RelKind,
)


class ModuleGraph:
    """Wraps a NetworkX DiGraph of module IMPORTS edges."""

    def __init__(self, graph: nx.DiGraph):
        self._g = graph

    @classmethod
    def from_architecture(cls, arch: ArchitectureGraph) -> "ModuleGraph":
        g = nx.DiGraph()
        for node in arch.nodes:
            if node.kind == NodeKind.MODULE:
                g.add_node(node.id, file_path=node.file_path)
        for edge in arch.edges:
            if edge.kind == RelKind.IMPORTS:
                g.add_edge(edge.source, edge.target)
        return cls(g)

    @property
    def nx_graph(self) -> nx.DiGraph:
        return self._g

    # --- centrality (task 1.2) ------------------------------------------
    def compute_centrality(self) -> dict[str, ModuleCentrality]:
        result: dict[str, ModuleCentrality] = {}
        if self._g.number_of_nodes() == 0:
            return result
        pagerank = self._pagerank()
        for node in self._g.nodes:
            result[node] = ModuleCentrality(
                module=node,
                in_degree=self._g.in_degree(node),
                out_degree=self._g.out_degree(node),
                pagerank=round(float(pagerank.get(node, 0.0)), 6),
            )
        return result

    def _pagerank(self) -> dict[str, float]:
        """PageRank with graceful fallbacks.

        Prefers NetworkX's default (numpy-backed) implementation, falls back to
        the pure-Python variant if numpy is unavailable, and finally to a
        degree-based approximation if both fail to converge.
        """
        try:
            return nx.pagerank(self._g)
        except ImportError:
            try:
                from networkx.algorithms.link_analysis.pagerank_alg import (
                    _pagerank_python,
                )

                return _pagerank_python(self._g)
            except Exception:
                pass
        except (nx.PowerIterationFailedConvergence, ZeroDivisionError):
            pass
        # Degree-based approximation as a last resort.
        n = self._g.number_of_nodes() or 1
        return {node: self._g.in_degree(node) / n for node in self._g.nodes}

    # --- dependency queries (task 1.7) ----------------------------------
    def direct_dependencies(self, module: str) -> list[str]:
        """Modules that ``module`` imports directly."""
        if module not in self._g:
            return []
        return sorted(self._g.successors(module))

    def transitive_dependencies(self, module: str) -> list[str]:
        """All modules ``module`` depends on, directly or indirectly."""
        if module not in self._g:
            return []
        return sorted(nx.descendants(self._g, module))

    def direct_dependents(self, module: str) -> list[str]:
        """Modules that directly import ``module``."""
        if module not in self._g:
            return []
        return sorted(self._g.predecessors(module))

    def blast_radius(self, module: str) -> list[str]:
        """Approximate blast radius: all modules transitively depending on
        ``module`` (its ancestors in the IMPORTS graph)."""
        if module not in self._g:
            return []
        return sorted(nx.ancestors(self._g, module))

    # --- centrality queries (task 1.8) ----------------------------------
    def high_centrality_modules(
        self, centrality: dict[str, ModuleCentrality], top_n: int = 10
    ) -> list[ModuleCentrality]:
        ranked = sorted(
            centrality.values(),
            key=lambda c: (c.pagerank, c.in_degree),
            reverse=True,
        )
        return ranked[:top_n]

    def high_centrality_low_coverage(
        self,
        centrality: dict[str, ModuleCentrality],
        coverage_by_module: dict[str, float],
        coverage_threshold: float,
    ) -> list[tuple[ModuleCentrality, float | None]]:
        """Candidates for the Test Coverage Gap agent (task 1.8, Req 5).

        Uses above-median centrality (pagerank) combined with below-threshold
        coverage. Coverage is optional (populated in Phase 5); modules with no
        coverage data are returned with ``None`` so callers can distinguish
        'low coverage' from 'unknown coverage'.
        """
        if not centrality:
            return []
        pageranks = sorted(c.pagerank for c in centrality.values())
        mid = len(pageranks) // 2
        median = (
            pageranks[mid]
            if len(pageranks) % 2
            else (pageranks[mid - 1] + pageranks[mid]) / 2
        )
        out: list[tuple[ModuleCentrality, float | None]] = []
        for mod, c in centrality.items():
            if c.pagerank < median:
                continue
            cov = coverage_by_module.get(mod)
            if cov is None or cov < coverage_threshold:
                out.append((c, cov))
        out.sort(key=lambda t: t[0].pagerank, reverse=True)
        return out
