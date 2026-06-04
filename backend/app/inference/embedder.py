from __future__ import annotations

import hashlib
import math
import re
from typing import List, Optional, Tuple

from app.inference.config import get_embed_model_id, get_embed_batch_size, get_vector_dims, resolve_backend


class Embedder:
    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.model_id = self._model_id_for(backend)
        self.device_label = self._device_label_for(backend)
        self._sentence_model = None

    def _model_id_for(self, backend: str) -> str:
        if backend == "hash":
            return "evidenceos-hash-v1"
        if backend == "coreml":
            return f"coreml-{get_embed_model_id()}"
        if backend == "sentence":
            return get_embed_model_id()
        return "none"

    def _device_label_for(self, backend: str) -> str:
        if backend == "coreml":
            return "Apple Neural Engine (Core ML)"
        if backend == "sentence":
            return "CPU (sentence-transformers)"
        if backend == "hash":
            return "CPU (hash vectors — no model download)"
        return "disabled"

    @classmethod
    def from_env(cls) -> "Embedder":
        backend = resolve_backend()
        if backend == "coreml":
            # Core ML bundles ship separately; fall back until export exists.
            backend = "sentence" if _sentence_available() else "hash"
        if backend == "sentence" and not _sentence_available():
            backend = "hash"
        return cls(backend)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.backend == "sentence":
            return self._embed_sentence(texts)
        return [self._embed_hash(text) for text in texts]

    def _embed_hash(self, text: str) -> List[float]:
        dims = get_vector_dims()
        vector = [0.0] * dims
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def _embed_sentence(self, texts: List[str]) -> List[List[float]]:
        model = self._get_sentence_model()
        batch_size = get_embed_batch_size()
        vectors: List[List[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            encoded = model.encode(batch, normalize_embeddings=True)
            vectors.extend([row.tolist() for row in encoded])
        return vectors

    def _get_sentence_model(self):
        if self._sentence_model is None:
            from sentence_transformers import SentenceTransformer

            self._sentence_model = SentenceTransformer(get_embed_model_id())
        return self._sentence_model


def _sentence_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except Exception:
        return False


def cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def top_similar_chunks(
    query_vector: List[float],
    chunks: List[Tuple[str, List[float], str, int]],
    limit: int,
) -> List[Tuple[float, str, int]]:
    scored: List[Tuple[float, str, int]] = []
    for chunk_id, vector, text, chunk_index in chunks:
        score = cosine_similarity(query_vector, vector)
        if score > 0:
            scored.append((score, text, chunk_index))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:limit]
