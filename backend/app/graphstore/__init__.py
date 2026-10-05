"""Graph store abstraction (Neo4j with in-memory fallback)."""

from app.graphstore.base import GraphStore
from app.graphstore.memory_store import InMemoryGraphStore
from app.graphstore.neo4j_store import Neo4jGraphStore, get_graph_store

__all__ = [
    "GraphStore",
    "InMemoryGraphStore",
    "Neo4jGraphStore",
    "get_graph_store",
]
