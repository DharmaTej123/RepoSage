"""Synthesis Agent (Phase 7).

Turns validated findings + reasoning artifacts into human-facing artifacts:

* onboarding guide (7.2),
* technical-debt report with combined ranking + per-finding source attribution
  (7.3),
* run-to-run diff of findings (7.4).

Evidence discipline (7.5, 7.6): synthesis distinguishes "analysis unavailable"
from "clean result", and every non-trivial claim either maps to a Finding /
Evidence record or is explicitly labeled an inference. Deterministic assembly
here does not fabricate; an optional LLM narrative layer (later) sits on top of
these structured artifacts and is likewise constrained to cite evidence.
"""

from app.synthesis.chunking import CodeChunk, chunk_repository
from app.synthesis.embeddings import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    get_embedding_provider,
)
from app.synthesis.diff import RunDiff, diff_runs
from app.synthesis.agent import SynthesisAgent

__all__ = [
    "CodeChunk",
    "chunk_repository",
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "get_embedding_provider",
    "RunDiff",
    "diff_runs",
    "SynthesisAgent",
]