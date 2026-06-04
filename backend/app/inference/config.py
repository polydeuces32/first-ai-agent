from __future__ import annotations

import os
import platform
import sys
from typing import Literal

InferenceBackend = Literal["none", "hash", "sentence", "coreml", "auto"]


def get_inference_backend() -> InferenceBackend:
    raw = os.getenv("INFERENCE_BACKEND", "auto").strip().lower()
    if raw in ("none", "hash", "sentence", "coreml", "auto"):
        return raw  # type: ignore[return-value]
    return "auto"


def inference_enabled() -> bool:
    return get_inference_backend() != "none"


def get_embed_model_id() -> str:
    return os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2").strip()


def get_chunk_size() -> int:
    return max(200, int(os.getenv("CHUNK_SIZE", "800")))


def get_chunk_overlap() -> int:
    return max(0, int(os.getenv("CHUNK_OVERLAP", "120")))


def get_embed_batch_size() -> int:
    return max(1, int(os.getenv("EMBED_BATCH_SIZE", "32")))


def get_vector_dims() -> int:
    return max(64, int(os.getenv("EMBED_VECTOR_DIMS", "384")))


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}


def resolve_backend() -> str:
    """Pick runtime backend from INFERENCE_BACKEND and platform."""
    configured = get_inference_backend()
    if configured == "none":
        return "none"
    if configured == "hash":
        return "hash"
    if configured == "sentence":
        return "sentence"
    if configured == "coreml":
        return "coreml"
    # auto
    if is_apple_silicon():
        try:
            import coremltools  # noqa: F401

            return "coreml"
        except Exception:
            pass
    try:
        import sentence_transformers  # noqa: F401

        return "sentence"
    except Exception:
        return "hash"
