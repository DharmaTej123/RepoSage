"""Architecture Mapper tests (Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analyzers.architecture_mapper import ArchitectureMapper
from app.analyzers.graph import ModuleGraph
from app.analyzers.models import NodeKind, RelKind
from app.graphstore.memory_store import InMemoryGraphStore


@pytest.fixture
def multi_module_repo(tmp_path: Path) -> Path:
    """A small package where imports form a clear dependency chain.

    pkg/
      __init__.py
      core.py          (imports pkg.utils)
      service.py       (imports pkg.core, pkg.utils)
      utils.py         (leaf)
      broken.py        (syntax error -> unparsable)
    main.py            (imports pkg.service)
    """
    root = tmp_path / "repo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "core.py").write_text(
        "from pkg import utils\n\n\nclass Engine:\n    def run(self):\n        return utils.helper()\n",
        encoding="utf-8",
    )
    (pkg / "service.py").write_text(
        "from pkg import core\nfrom pkg import utils\n\n\ndef serve():\n    return core.Engine().run() + utils.helper()\n",
        encoding="utf-8",
    )
    (pkg / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    (root / "main.py").write_text(
        "from pkg import service\n\n\ndef entry():\n    return service.serve()\n",
        encoding="utf-8",
    )
    return root


def _map(root: Path):
    return ArchitectureMapper(root, revision="deadbeef" * 5).run()


def test_modules_and_imports_detected(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    module_ids = set(arch.module_ids())
    assert {"pkg", "pkg.core", "pkg.service", "pkg.utils", "main"} <= module_ids

    import_pairs = {(e.source, e.target) for e in arch.import_edges()}
    assert ("pkg.core", "pkg.utils") in import_pairs
    assert ("pkg.service", "pkg.core") in import_pairs
    assert ("pkg.service", "pkg.utils") in import_pairs
    assert ("main", "pkg.service") in import_pairs


def test_unparsable_file_recorded_not_fatal(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    unparsed_paths = {u.file_path for u in arch.unparsed}
    assert any(p.endswith("broken.py") for p in unparsed_paths)
    # Rest of the graph still built.
    assert "pkg.service" in arch.module_ids()


def test_classes_and_functions_captured(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    class_nodes = {n.name for n in arch.nodes if n.kind == NodeKind.CLASS}
    fn_nodes = {n.name for n in arch.nodes if n.kind == NodeKind.FUNCTION}
    assert "Engine" in class_nodes
    assert "serve" in fn_nodes
    contains = [e for e in arch.edges if e.kind == RelKind.CONTAINS]
    assert any(e.target.endswith(":Engine") for e in contains)


def test_provenance_present(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    for e in arch.import_edges():
        assert e.file_path is not None
        assert e.lineno is not None and e.lineno >= 1


def test_centrality_ranks_utils_highest(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    c = arch.centrality
    # utils is imported by core and service -> highest in-degree among leaves.
    assert c["pkg.utils"].in_degree >= 2
    assert c["main"].in_degree == 0  # nothing imports main


def test_dependency_and_blast_radius_queries(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    g = ModuleGraph.from_architecture(arch)

    assert set(g.direct_dependencies("pkg.service")) >= {"pkg.core", "pkg.utils"}
    assert "pkg.utils" in g.transitive_dependencies("main")
    # Blast radius of changing utils = everything that (transitively) imports it.
    br = set(g.blast_radius("pkg.utils"))
    assert {"pkg.core", "pkg.service", "main"} <= br


def test_high_centrality_query(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    g = ModuleGraph.from_architecture(arch)
    top = g.high_centrality_modules(arch.centrality, top_n=3)
    assert top  # non-empty
    assert top[0].pagerank >= top[-1].pagerank


def test_high_centrality_low_coverage_distinguishes_unknown(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    g = ModuleGraph.from_architecture(arch)
    # No coverage data yet -> central modules returned with None coverage.
    candidates = g.high_centrality_low_coverage(
        arch.centrality, coverage_by_module={}, coverage_threshold=0.5
    )
    assert candidates
    assert all(cov is None for _, cov in candidates)


def test_in_memory_graph_store_roundtrip(multi_module_repo: Path):
    arch = _map(multi_module_repo)
    store = InMemoryGraphStore()
    store.persist_architecture("repo-1", arch)
    deps = store.direct_dependencies("repo-1", arch.revision, "pkg.service")
    assert "pkg.core" in deps
    br = store.blast_radius("repo-1", arch.revision, "pkg.utils")
    assert "main" in br
    top = store.high_centrality_modules("repo-1", arch.revision, top_n=2)
    assert len(top) <= 2
