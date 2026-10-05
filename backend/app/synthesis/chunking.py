"""Deterministic code + doc chunking for pgvector indexing (task 7.1).

Python files are chunked at the AST level (one chunk per top-level class /
function, plus a module-header chunk). Markdown/text docs are chunked by a
sliding window over lines. Every chunk carries provenance (file path + line
range) so retrieved context can be cited back to source (Req 11).

No embeddings are computed here; that is the embedding provider's job. Chunking
is deterministic and testable without any external service.
"""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CODE_SUFFIXES = {".py"}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
EXCLUDED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", "site-packages",
    ".tox", ".mypy_cache", ".pytest_cache", "build", "dist", ".eggs",
}
DOC_WINDOW_LINES = 40
DOC_STRIDE_LINES = 30


@dataclass
class CodeChunk:
    id: str
    kind: str            # "code" | "doc"
    file_path: str       # repo-relative posix
    start_line: int
    end_line: int
    symbol: str | None   # module/class/function name for code
    text: str
    metadata: dict = field(default_factory=dict)


def _chunk_id(file_path: str, start: int, end: int) -> str:
    h = hashlib.sha1(f"{file_path}:{start}:{end}".encode()).hexdigest()[:16]
    return f"chunk-{h}"


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & EXCLUDED_DIRS:
            continue
        if path.suffix in CODE_SUFFIXES or path.suffix in DOC_SUFFIXES:
            yield path


def _chunk_python(path: Path, rel: str) -> list[CodeChunk]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    chunks: list[CodeChunk] = []

    # Module header chunk: everything before the first top-level def/class.
    first_body_line = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first_body_line = node.lineno
            break
    header_end = (first_body_line - 1) if first_body_line else min(len(lines), DOC_WINDOW_LINES)
    if header_end > 0:
        text = "\n".join(lines[:header_end]).strip()
        if text:
            chunks.append(CodeChunk(
                id=_chunk_id(rel, 1, header_end), kind="code", file_path=rel,
                start_line=1, end_line=header_end, symbol="<module>", text=text,
            ))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            text = "\n".join(lines[start - 1:end])
            chunks.append(CodeChunk(
                id=_chunk_id(rel, start, end), kind="code", file_path=rel,
                start_line=start, end_line=end, symbol=node.name, text=text,
                metadata={"node_type": type(node).__name__},
            ))
    return chunks


def _chunk_doc(path: Path, rel: str) -> list[CodeChunk]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    chunks: list[CodeChunk] = []
    i = 0
    n = len(lines)
    while i < n:
        window = lines[i:i + DOC_WINDOW_LINES]
        text = "\n".join(window).strip()
        if text:
            start = i + 1
            end = min(i + DOC_WINDOW_LINES, n)
            chunks.append(CodeChunk(
                id=_chunk_id(rel, start, end), kind="doc", file_path=rel,
                start_line=start, end_line=end, symbol=None, text=text,
            ))
        if i + DOC_WINDOW_LINES >= n:
            break
        i += DOC_STRIDE_LINES
    return chunks


def chunk_repository(repo_root: Path) -> list[CodeChunk]:
    root = Path(repo_root).resolve()
    chunks: list[CodeChunk] = []
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix()
        if path.suffix in CODE_SUFFIXES:
            chunks.extend(_chunk_python(path, rel))
        else:
            chunks.extend(_chunk_doc(path, rel))
    logger.info("Chunked repository into %d chunks", len(chunks))
    return chunks