"""Embedding provider abstraction (task 7.1).

Production would use a real embeddings model (OpenAI/local). For dev/tests
without an API key we provide a deterministic HASHING embedder so semantic
retrieval plumbing is fully exercisable offline. The provider is selected via
configuration; the hashing provider is the safe default when no key is set.

The hashing embedder is deterministic and reproducible (same text -> same
vector), which is exactly what tests need. It is NOT semantically meaningful,
so it is only for local development / plumbing tests, never for evaluation
numbers.
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Protocol, runtime_checkable

from app.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_DIM = 256


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbeddingProvider:
    """Deterministic bag-of-hashed-tokens embedding, L2-normalized."""

    def __init__(self, dim: int = DEFAULT_DIM):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, dot))  # both are unit vectors from HashingEmbedder


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Return the configured provider; hashing fallback when no key/model set."""
    # v1: no external key wired; use deterministic hashing provider. This keeps
    # the pipeline fully functional offline and is swappable later.
    logger.info("Using HashingEmbeddingProvider (offline, deterministic).")
    return HashingEmbeddingProvider()