"""Text embeddings for discovery (MV19), on CPU at tier 3.

* ``FastEmbedder``: fastembed (Apache-2.0) with ``BAAI/bge-small-en-v1.5``
  (384 dimensions, ONNX on CPU), used when fastembed is installed.
* ``HashingEmbedder``: a dependency-free fallback (feature hashing of words
  and word pairs, 384 dimensions). Rows remember their model, and a query is
  only compared with rows of the same model.
``OTT_DISCOVERY_EMBEDDER`` picks one: ``fastembed``, ``hashing`` or empty
(auto: fastembed when it loads, else hashing). fastembed is installed on the
API and worker images (``requirements.txt``); the model downloads once into
``FASTEMBED_CACHE_PATH`` (the worker's model-cache volume). When it cannot
load, the hashing embedder takes over and the reason is logged.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from typing import Protocol, Sequence

import numpy as np
from loguru import logger

DIM = 384
_WORD = re.compile(r"[\w']+", re.UNICODE)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class HashingEmbedder:
    name = "hashing-384-v1"
    dim = DIM

    def _one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        words = [w.lower() for w in _WORD.findall(text or "")]
        features = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        return vector

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return _normalise(np.stack([self._one(t) for t in texts])) if texts else np.zeros((0, self.dim))


class FastEmbedder:
    name = "bge-small-en-v1.5"
    dim = DIM

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        cache = (os.getenv("FASTEMBED_CACHE_PATH") or "").strip() or None
        self._model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=cache)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim))
        return _normalise(np.array(list(self._model.embed(list(texts))), dtype=np.float32))


CHOICES = ("", "auto", "fastembed", "hashing")


def choice() -> str:
    value = (os.getenv("OTT_DISCOVERY_EMBEDDER") or "").strip().lower()
    return value if value in CHOICES else ""


@lru_cache(maxsize=1)
def default_embedder() -> Embedder:
    if choice() != "hashing":
        try:
            return FastEmbedder()
        except Exception as exc:  # noqa: BLE001 - fastembed missing or its model not downloadable here
            logger.warning(f"ott discovery: fastembed unavailable ({type(exc).__name__}: {exc}); using hashing")
    return HashingEmbedder()


def by_name(name: str) -> Embedder | None:
    """The embedder that wrote rows named ``name``, when this process can run it."""
    current = default_embedder()
    if current.name == name:
        return current
    if name == HashingEmbedder.name:
        return HashingEmbedder()
    return None


__all__ = ["CHOICES", "DIM", "Embedder", "FastEmbedder", "HashingEmbedder", "by_name", "choice", "default_embedder"]
