"""Text embeddings and reranking. Production uses local ONNX models (fastembed); tests use a
deterministic hashing embedder so no model is ever downloaded in unit tests."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from pathlib import Path
from typing import Any, Protocol


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, query: str) -> list[float]:
        """Embedding for a *search query* against passages (asymmetric retrieval)."""
        ...


class Reranker(Protocol):
    async def scores(self, query: str, texts: list[str]) -> list[float]: ...


def _normalise(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


# Query instruction from the BGE model card, for retrieving passages with short queries.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class FastEmbedder:
    """``BAAI/bge-small-en-v1.5`` (384-d) by default. Model loading is lazy and thread-offloaded."""

    def __init__(self, model: str, cache_dir: Path, dim: int) -> None:
        self.model_name, self.cache_dir, self.dim = model, cache_dir, dim
        self._model: Any = None
        self.query_prefix = BGE_QUERY_PREFIX if model.startswith("BAAI/bge") else ""

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name, cache_dir=str(self.cache_dir))
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def run() -> list[list[float]]:
            return [_normalise([float(x) for x in v]) for v in self._load().embed(texts)]

        return await asyncio.to_thread(run)

    async def embed_query(self, query: str) -> list[float]:
        (vec,) = await self.embed([self.query_prefix + query])
        return vec


class CrossEncoderReranker:
    def __init__(self, model: str, cache_dir: Path) -> None:
        self.model_name, self.cache_dir = model, cache_dir
        self._model: Any = None

    async def scores(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []

        def run() -> list[float]:
            if self._model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._model = TextCrossEncoder(self.model_name, cache_dir=str(self.cache_dir))
            return [float(s) for s in self._model.rerank(query, texts)]

        return await asyncio.to_thread(run)


_TOKEN = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder (tests only; meaningful lexical overlap)."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in _TOKEN.findall(text.lower()):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
                v[h % self.dim] += 1.0 if (h >> 63) else -1.0
            out.append(_normalise(v))
        return out

    async def embed_query(self, query: str) -> list[float]:
        (vec,) = await self.embed([query])
        return vec


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
