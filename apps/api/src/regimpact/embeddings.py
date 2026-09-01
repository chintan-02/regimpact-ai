"""Embedding provider boundary and deterministic local baseline."""

from __future__ import annotations

import math
import re
from hashlib import blake2b
from importlib import import_module
from typing import Any, Protocol

EMBEDDING_DIMENSIONS = 384
EMBEDDING_MODEL_ID = "feature-hash-384-v1"
_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class FeatureHashEmbeddingProvider:
    """Reproducible dependency-free baseline; not a neural semantic model."""

    model_id = EMBEDDING_MODEL_ID
    dimensions = EMBEDDING_DIMENSIONS

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        output: list[tuple[float, ...]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in _TOKEN.findall(text.lower()):
                digest = blake2b(token.encode(), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "big") % self.dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[bucket] += sign
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            output.append(tuple(round(value / norm, 8) for value in vector))
        return tuple(output)


class SentenceTransformerEmbeddingProvider:
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            module = import_module("sentence_transformers")
        except ImportError as exc:
            raise RuntimeError("sentence-transformers provider is not installed") from exc
        self.model_id = model_name
        self._model: Any = module.SentenceTransformer(model_name)
        if self._model.get_sentence_embedding_dimension() != self.dimensions:
            raise RuntimeError("embedding model dimensions do not match the search index")

    def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return tuple(tuple(float(value) for value in vector) for vector in vectors)


def configured_embedding_provider(
    *, environment: str, provider_name: str, model_name: str
) -> EmbeddingProvider:
    if provider_name == "feature_hash":
        if environment != "local":
            raise RuntimeError("feature-hash embeddings are restricted to local environments")
        return FeatureHashEmbeddingProvider()
    if provider_name == "sentence_transformer":
        return SentenceTransformerEmbeddingProvider(model_name)
    raise RuntimeError("unsupported embedding provider")
