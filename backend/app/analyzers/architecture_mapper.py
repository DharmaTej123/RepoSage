"""Architecture Mapper — deterministic orchestration of Phase 1 analysis.

Ties together the AST parser, node/edge construction, and centrality into a
single :class:`ArchitectureGraph` for a given repository revision. This is a
plain deterministic service (no LLM); a specialist agent later turns its output
into structured findings.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analyzers.ast_parser import ASTArchitectureParser
from app.analyzers.graph import ModuleGraph
from app.analyzers.models import ArchitectureGraph

logger = logging.getLogger(__name__)


class ArchitectureMapper:
    def __init__(self, repo_root: Path, revision: str):
        self.repo_root = Path(repo_root)
        self.revision = revision

    def run(self) -> ArchitectureGraph:
        parser = ASTArchitectureParser(self.repo_root)
        modules, unparsed = parser.parse()
        nodes, edges = parser.build_nodes_edges(modules)

        arch = ArchitectureGraph(
            revision=self.revision,
            nodes=nodes,
            edges=edges,
            unparsed=unparsed,
        )
        arch.centrality = ModuleGraph.from_architecture(arch).compute_centrality()

        logger.info(
            "Architecture mapped: %d modules, %d edges, %d unparsed (rev=%s)",
            len(arch.module_ids()),
            len(arch.import_edges()),
            len(unparsed),
            self.revision[:12] if self.revision else "?",
        )
        return arch

    def module_graph(self, arch: ArchitectureGraph) -> ModuleGraph:
        return ModuleGraph.from_architecture(arch)
