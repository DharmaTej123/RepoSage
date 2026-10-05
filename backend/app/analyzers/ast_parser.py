"""AST-based import/structure parser (tasks 1.1, 1.4, 1.5, 1.6).

Given a repository working directory, produce:
* module nodes (one per .py file / package),
* IMPORTS edges between *internal* modules (external imports are ignored here;
  dependency risk is a separate agent),
* CONTAINS / DEFINES edges for classes and module-level functions,
* provenance (source file + line) on every node and edge,
* a list of files that could not be parsed (recorded, not fatal — Req 2).

Import resolution is intentionally conservative: we only create an edge when
the imported name resolves to a module that actually exists in the repo. This
keeps the graph deterministic and avoids inventing edges to third-party
packages.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.analyzers.models import (
    GraphEdge,
    GraphNode,
    NodeKind,
    RelKind,
    UnparsedFile,
)

logger = logging.getLogger(__name__)

# Directories we never treat as source (vendored / VCS / build artifacts).
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", "site-packages", ".tox", ".mypy_cache", ".pytest_cache",
    "build", "dist", ".eggs",
}


@dataclass
class ParsedModule:
    module: str          # dotted module id, e.g. "pkg.sub.mod"
    file_path: str       # repo-relative posix path
    is_package: bool
    imports: list[tuple[str, int]] = field(default_factory=list)  # (target, lineno) unresolved
    classes: list[tuple[str, int]] = field(default_factory=list)
    functions: list[tuple[str, int]] = field(default_factory=list)


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        parts = set(path.relative_to(root).parts)
        if parts & EXCLUDED_DIRS:
            continue
        yield path


def _module_name_for(path: Path, root: Path) -> str:
    """Compute a dotted module name for a file relative to the repo root.

    ``__init__.py`` maps to its package (the parent directory path).
    """
    rel = path.relative_to(root)
    if rel.name == "__init__.py":
        parts = rel.parent.parts
    else:
        parts = rel.with_suffix("").parts
    return ".".join(parts)


class ImportVisitor(ast.NodeVisitor):
    """Collect imports, classes, and module-level functions with line numbers."""

    def __init__(self, module: str, is_package: bool):
        self.module = module
        self.is_package = is_package
        self.imports: list[tuple[str, int]] = []
        self.classes: list[tuple[str, int]] = []
        self.functions: list[tuple[str, int]] = []
        self._depth = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append((alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = self._resolve_relative(node.module, node.level)
        if base is None:
            return
        # Record the module itself; also record module.name for each imported
        # symbol so `from pkg import submod` resolves to pkg.submod if it exists.
        self.imports.append((base, node.lineno))
        for alias in node.names:
            if alias.name != "*":
                self.imports.append((f"{base}.{alias.name}", node.lineno))

    def _resolve_relative(self, module: str | None, level: int) -> str | None:
        if level == 0:
            return module
        # Relative import: climb from the current package.
        pkg_parts = self.module.split(".")
        if not self.is_package:
            pkg_parts = pkg_parts[:-1]  # module lives inside its package
        # level 1 = current package; each extra level climbs one more.
        climb = level - 1
        if climb > len(pkg_parts):
            return None
        base_parts = pkg_parts[: len(pkg_parts) - climb] if climb else pkg_parts
        if module:
            base_parts = [*base_parts, *module.split(".")]
        return ".".join(base_parts) if base_parts else None

    # Only capture *module-level* classes/functions (depth tracking).
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._depth == 0:
            self.classes.append((node.name, node.lineno))
        self._descend(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._depth == 0:
            self.functions.append((node.name, node.lineno))
        self._descend(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._depth == 0:
            self.functions.append((node.name, node.lineno))
        self._descend(node)

    def _descend(self, node: ast.AST) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1


class ASTArchitectureParser:
    """Parses a repository into module nodes/edges + structure."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()

    def parse(self) -> tuple[list[ParsedModule], list[UnparsedFile]]:
        modules: list[ParsedModule] = []
        unparsed: list[UnparsedFile] = []

        for file_path in _iter_python_files(self.repo_root):
            rel = file_path.relative_to(self.repo_root).as_posix()
            try:
                source = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                unparsed.append(UnparsedFile(file_path=rel, reason=f"read error: {exc}"))
                logger.warning("Unreadable file %s: %s", rel, exc)
                continue

            try:
                tree = ast.parse(source, filename=rel)
            except SyntaxError as exc:
                unparsed.append(UnparsedFile(file_path=rel, reason=f"syntax error: {exc}"))
                logger.warning("Unparsable file %s: %s", rel, exc)
                continue

            module_name = _module_name_for(file_path, self.repo_root)
            is_package = file_path.name == "__init__.py"
            visitor = ImportVisitor(module_name, is_package)
            visitor.visit(tree)
            modules.append(
                ParsedModule(
                    module=module_name,
                    file_path=rel,
                    is_package=is_package,
                    imports=visitor.imports,
                    classes=visitor.classes,
                    functions=visitor.functions,
                )
            )

        return modules, unparsed

    def build_nodes_edges(
        self, modules: list[ParsedModule]
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Resolve imports against the set of internal modules and emit graph
        nodes/edges with provenance."""
        internal = {m.module: m for m in modules}
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_import_edges: set[tuple[str, str]] = set()

        for m in modules:
            nodes.append(
                GraphNode(
                    id=m.module or m.file_path,
                    kind=NodeKind.MODULE,
                    name=m.module or m.file_path,
                    file_path=m.file_path,
                    lineno=1,
                    metadata={"is_package": m.is_package},
                )
            )

            # IMPORTS edges (internal only, deduped).
            for target, lineno in m.imports:
                resolved = self._resolve_internal(target, internal)
                if resolved is None or resolved == m.module:
                    continue
                key = (m.module, resolved)
                if key in seen_import_edges:
                    continue
                seen_import_edges.add(key)
                edges.append(
                    GraphEdge(
                        source=m.module,
                        target=resolved,
                        kind=RelKind.IMPORTS,
                        file_path=m.file_path,
                        lineno=lineno,
                    )
                )

            # CONTAINS (class) / DEFINES (function) with provenance.
            for cls_name, lineno in m.classes:
                cls_id = f"{m.module}:{cls_name}"
                nodes.append(
                    GraphNode(
                        id=cls_id,
                        kind=NodeKind.CLASS,
                        name=cls_name,
                        file_path=m.file_path,
                        lineno=lineno,
                    )
                )
                edges.append(
                    GraphEdge(
                        source=m.module, target=cls_id, kind=RelKind.CONTAINS,
                        file_path=m.file_path, lineno=lineno,
                    )
                )
            for fn_name, lineno in m.functions:
                fn_id = f"{m.module}:{fn_name}"
                nodes.append(
                    GraphNode(
                        id=fn_id, kind=NodeKind.FUNCTION, name=fn_name,
                        file_path=m.file_path, lineno=lineno,
                    )
                )
                edges.append(
                    GraphEdge(
                        source=m.module, target=fn_id, kind=RelKind.DEFINES,
                        file_path=m.file_path, lineno=lineno,
                    )
                )

        return nodes, edges

    @staticmethod
    def _resolve_internal(
        target: str, internal: dict[str, ParsedModule]
    ) -> str | None:
        """Resolve an imported dotted name to an internal module id.

        Tries the full name, then progressively shorter prefixes (so
        ``pkg.mod.symbol`` resolves to ``pkg.mod`` when ``symbol`` is not a
        module). Returns None for external / unresolved imports.
        """
        if target in internal:
            return target
        parts = target.split(".")
        for i in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in internal:
                return candidate
        return None
