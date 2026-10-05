"""Retrieval layer over graph / vector / git / source (tasks 8.1, 8.3-8.5).

Each retriever returns a list of ``Retrieved`` items, each carrying the payload
plus an ``Evidence`` record so answers can cite sources. Retrievers operate on
the in-memory analysis results (architecture graph, ownership report, code
chunks) built in earlier phases, so the copilot works offline and its answers
remain provenance-backed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.graph import ModuleGraph
from app.analyzers.models import ArchitectureGraph
from app.analyzers.githistory.models import OwnershipReport
from app.schemas.finding import Evidence, EvidenceSourceType
from app.synthesis.chunking import CodeChunk
from app.synthesis.embeddings import EmbeddingProvider, cosine_similarity


@dataclass
class Retrieved:
    text: str
    evidence: Evidence
    score: float = 1.0
    metadata: dict = field(default_factory=dict)


class GraphRetriever:
    """Answers dependency / blast-radius / centrality questions (8.3)."""

    def __init__(self, architecture: ArchitectureGraph):
        self._arch = architecture
        self._graph = ModuleGraph.from_architecture(architecture)

    def _file_for(self, module: str) -> str | None:
        node = next((n for n in self._arch.nodes if n.id == module), None)
        return node.file_path if node else None

    def dependents(self, module: str) -> list[Retrieved]:
        deps = self._graph.direct_dependents(module)
        return [self._ret(module, d, "is imported by") for d in deps]

    def dependencies(self, module: str) -> list[Retrieved]:
        deps = self._graph.direct_dependencies(module)
        return [self._ret(module, d, "imports") for d in deps]

    def blast_radius(self, module: str) -> list[Retrieved]:
        radius = self._graph.blast_radius(module)
        return [self._ret(module, d, "would be affected by changing") for d in radius]

    def central_modules(self, top_n: int = 8) -> list[Retrieved]:
        top = self._graph.high_centrality_modules(self._arch.centrality, top_n=top_n)
        out = []
        for c in top:
            out.append(Retrieved(
                text=f"{c.module} (in-degree {c.in_degree}, pagerank {c.pagerank:.4f})",
                evidence=Evidence(
                    source_type=EvidenceSourceType.GRAPH, source=f"module:{c.module}",
                    location=self._file_for(c.module),
                    metadata={"in_degree": c.in_degree, "pagerank": c.pagerank},
                ),
                score=c.pagerank,
                metadata={"module": c.module},
            ))
        return out

    def _ret(self, a: str, b: str, rel: str) -> Retrieved:
        return Retrieved(
            text=f"{b} {rel} {a}",
            evidence=Evidence(
                source_type=EvidenceSourceType.GRAPH,
                source=f"module:{b}", location=self._file_for(b),
            ),
            metadata={"module": b},
        )


class GitRetriever:
    """Answers ownership / history questions (8.4)."""

    def __init__(self, ownership: OwnershipReport):
        self._ownership = ownership

    def contributors(self, module: str) -> list[Retrieved]:
        m = next((x for x in self._ownership.modules if x.module == module), None)
        if m is None:
            return []
        out = []
        for c in m.contributors[:5]:
            out.append(Retrieved(
                text=(f"{c.author_name} <{c.author_email}>: {c.commits} commits "
                      f"(historical contribution, not formal ownership)"),
                evidence=Evidence(
                    source_type=EvidenceSourceType.GIT,
                    source=f"git-history:{module}",
                    metadata={"commits": c.commits, "share": m.primary_contributor_share},
                ),
                score=float(c.commits),
                metadata={"module": module},
            ))
        return out


class VectorRetriever:
    """Semantic retrieval over code/doc chunks (8.1)."""

    def __init__(self, chunks: list[CodeChunk], provider: EmbeddingProvider):
        self._provider = provider
        self._chunks = chunks
        texts = [c.text for c in chunks]
        self._vectors = provider.embed(texts) if texts else []

    def search(self, query: str, top_k: int = 5) -> list[Retrieved]:
        if not self._chunks:
            return []
        qv = self._provider.embed([query])[0]
        scored = []
        for chunk, vec in zip(self._chunks, self._vectors):
            scored.append((cosine_similarity(qv, vec), chunk))
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for score, chunk in scored[:top_k]:
            out.append(Retrieved(
                text=chunk.text[:500],
                evidence=Evidence(
                    source_type=EvidenceSourceType.FILE, source=chunk.file_path,
                    location=f"L{chunk.start_line}-L{chunk.end_line}",
                    excerpt=(chunk.symbol or None),
                ),
                score=round(float(score), 4),
                metadata={"symbol": chunk.symbol, "file": chunk.file_path},
            ))
        return out


class SourceRetriever:
    """Direct source lookup by module/file (8.1)."""

    def __init__(self, repo_root: Path, architecture: ArchitectureGraph | None = None):
        self._root = Path(repo_root)
        self._arch = architecture

    def get_module_source(self, module: str, max_lines: int = 60) -> list[Retrieved]:
        file_path = None
        if self._arch is not None:
            node = next((n for n in self._arch.nodes if n.id == module), None)
            file_path = node.file_path if node else None
        if file_path is None:
            file_path = module.replace(".", "/") + ".py"
        full = self._root / file_path
        if not full.exists():
            return []
        try:
            lines = full.read_text(encoding="utf-8").splitlines()[:max_lines]
        except OSError:
            return []
        return [Retrieved(
            text="\n".join(lines),
            evidence=Evidence(
                source_type=EvidenceSourceType.FILE, source=file_path,
                location=f"L1-L{min(max_lines, len(lines))}",
            ),
            metadata={"module": module},
        )]