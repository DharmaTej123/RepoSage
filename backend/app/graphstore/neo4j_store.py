"""Neo4j-backed structural graph store (tasks 1.3, 1.7, 1.8).

Persists the architecture graph using the relationship model from design.md
section 5 and answers dependency / blast-radius / centrality queries in Cypher.

Nodes carry ``repo_id`` and ``revision`` properties so multiple runs of the
same repo coexist and every relationship is revision-scoped (provenance).

``get_graph_store`` returns a Neo4j store if a connection succeeds, otherwise
an :class:`InMemoryGraphStore` so the pipeline degrades gracefully when Neo4j
is not running (e.g. local dev without Docker). This is a deliberate
availability tradeoff, not silent data loss: the caller can inspect the
returned type.
"""

from __future__ import annotations

import logging

from app.analyzers.models import (
    ArchitectureGraph,
    ModuleCentrality,
    NodeKind,
    RelKind,
)
from app.config import Settings, get_settings
from app.graphstore.memory_store import InMemoryGraphStore

logger = logging.getLogger(__name__)


class Neo4jGraphStore:
    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase  # imported lazily

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._driver.verify_connectivity()

    # --- persistence (task 1.3) -----------------------------------------
    def persist_architecture(self, repo_id: str, arch: ArchitectureGraph) -> None:
        rev = arch.revision
        with self._driver.session() as session:
            # Idempotent per (repo, revision): clear then rewrite.
            session.run(
                "MATCH (n {repo_id:$repo_id, revision:$rev}) DETACH DELETE n",
                repo_id=repo_id, rev=rev,
            )
            # Module nodes with centrality.
            for node in arch.nodes:
                if node.kind != NodeKind.MODULE:
                    continue
                c = arch.centrality.get(node.id)
                session.run(
                    """
                    CREATE (m:Module {
                        id:$id, name:$name, repo_id:$repo_id, revision:$rev,
                        file_path:$file_path,
                        in_degree:$in_degree, out_degree:$out_degree,
                        pagerank:$pagerank
                    })
                    """,
                    id=node.id, name=node.name, repo_id=repo_id, rev=rev,
                    file_path=node.file_path,
                    in_degree=(c.in_degree if c else 0),
                    out_degree=(c.out_degree if c else 0),
                    pagerank=(c.pagerank if c else 0.0),
                )
            # Class/function nodes.
            for node in arch.nodes:
                if node.kind in (NodeKind.CLASS, NodeKind.FUNCTION):
                    label = "Class" if node.kind == NodeKind.CLASS else "Function"
                    session.run(
                        f"CREATE (n:{label} {{id:$id, name:$name, repo_id:$repo_id, "
                        f"revision:$rev, file_path:$file_path, lineno:$lineno}})",
                        id=node.id, name=node.name, repo_id=repo_id, rev=rev,
                        file_path=node.file_path, lineno=node.lineno,
                    )
            # Relationships with provenance.
            for edge in arch.edges:
                rel = edge.kind.value
                session.run(
                    f"""
                    MATCH (a {{id:$src, repo_id:$repo_id, revision:$rev}})
                    MATCH (b {{id:$dst, repo_id:$repo_id, revision:$rev}})
                    CREATE (a)-[:{rel} {{file_path:$file_path, lineno:$lineno}}]->(b)
                    """,
                    src=edge.source, dst=edge.target, repo_id=repo_id, rev=rev,
                    file_path=edge.file_path, lineno=edge.lineno,
                )
        logger.info("Persisted architecture to Neo4j (repo=%s rev=%s)", repo_id, rev[:12])

    # --- queries (tasks 1.7 / 1.8) --------------------------------------
    def direct_dependencies(self, repo_id: str, revision: str, module: str) -> list[str]:
        q = (
            "MATCH (m:Module {id:$id, repo_id:$repo_id, revision:$rev})"
            "-[:IMPORTS]->(d:Module) RETURN d.id AS id ORDER BY id"
        )
        return self._ids(q, id=module, repo_id=repo_id, rev=revision)

    def transitive_dependencies(self, repo_id: str, revision: str, module: str) -> list[str]:
        q = (
            "MATCH (m:Module {id:$id, repo_id:$repo_id, revision:$rev})"
            "-[:IMPORTS*1..]->(d:Module) RETURN DISTINCT d.id AS id ORDER BY id"
        )
        return self._ids(q, id=module, repo_id=repo_id, rev=revision)

    def blast_radius(self, repo_id: str, revision: str, module: str) -> list[str]:
        # dependents (ancestors): who imports this, transitively.
        q = (
            "MATCH (d:Module)-[:IMPORTS*1..]->(m:Module "
            "{id:$id, repo_id:$repo_id, revision:$rev}) "
            "RETURN DISTINCT d.id AS id ORDER BY id"
        )
        return self._ids(q, id=module, repo_id=repo_id, rev=revision)

    def high_centrality_modules(
        self, repo_id: str, revision: str, top_n: int = 10
    ) -> list[ModuleCentrality]:
        q = (
            "MATCH (m:Module {repo_id:$repo_id, revision:$rev}) "
            "RETURN m.id AS id, m.in_degree AS ind, m.out_degree AS outd, "
            "m.pagerank AS pr ORDER BY pr DESC, ind DESC LIMIT $top_n"
        )
        with self._driver.session() as session:
            rows = session.run(q, repo_id=repo_id, rev=revision, top_n=top_n)
            return [
                ModuleCentrality(
                    module=r["id"], in_degree=r["ind"] or 0,
                    out_degree=r["outd"] or 0, pagerank=r["pr"] or 0.0,
                )
                for r in rows
            ]

    def _ids(self, query: str, **params) -> list[str]:
        with self._driver.session() as session:
            return [r["id"] for r in session.run(query, **params)]

    def close(self) -> None:
        self._driver.close()


def get_graph_store(settings: Settings | None = None):
    """Return a Neo4j store, or an in-memory fallback if unreachable."""
    settings = settings or get_settings()
    try:
        return Neo4jGraphStore(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
    except Exception as exc:  # driver import error / connectivity failure
        logger.warning(
            "Neo4j unavailable (%s); using in-memory graph store fallback.", exc
        )
        return InMemoryGraphStore()
