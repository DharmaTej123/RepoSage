"""Data models for the architecture graph (Phase 1).

These are deterministic, provenance-carrying structures produced by the
Architecture Mapper. They are storage-agnostic: the same model is used to build
the in-memory NetworkX graph, to persist to Neo4j, and to serialize for the
frontend graph endpoint.

Provenance (Req 2): every node and relationship records the source file /
location and the analyzed revision so any downstream claim can be traced back.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    MODULE = "module"
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    PACKAGE = "package"      # external dependency (linked in later phases)
    DEVELOPER = "developer"  # git author (historical contributor)
    COMMIT = "commit"        # git commit


class RelKind(str, Enum):
    IMPORTS = "IMPORTS"      # module -> module
    CONTAINS = "CONTAINS"    # file -> module, module -> class, class -> function
    DEFINES = "DEFINES"      # module -> function (module-level)
    AUTHORED = "AUTHORED"    # developer -> commit
    TOUCHED = "TOUCHED"      # commit -> module (changed a file in that module)


class GraphNode(BaseModel):
    id: str = Field(..., description="Stable node id, e.g. module dotted path.")
    kind: NodeKind
    name: str
    # Provenance
    file_path: str | None = None  # repo-relative
    lineno: int | None = None
    metadata: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: RelKind
    # Provenance for the relationship itself (Req 2 / task 1.6).
    file_path: str | None = None
    lineno: int | None = None
    metadata: dict = Field(default_factory=dict)


class UnparsedFile(BaseModel):
    """A file that could not be parsed; recorded rather than aborting (Req 2)."""

    file_path: str
    reason: str


class ModuleCentrality(BaseModel):
    module: str
    in_degree: int = 0
    out_degree: int = 0
    pagerank: float = 0.0


class ArchitectureGraph(BaseModel):
    """Complete deterministic architecture-mapping result for one revision."""

    revision: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    centrality: dict[str, ModuleCentrality] = Field(default_factory=dict)
    unparsed: list[UnparsedFile] = Field(default_factory=list)

    # --- convenience accessors ---
    def module_ids(self) -> list[str]:
        return [n.id for n in self.nodes if n.kind == NodeKind.MODULE]

    def import_edges(self) -> list[GraphEdge]:
        return [e for e in self.edges if e.kind == RelKind.IMPORTS]
