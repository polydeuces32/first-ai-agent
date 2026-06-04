from __future__ import annotations

from typing import Any, Dict, List

from app.inference.config import (
    get_chunk_overlap,
    get_chunk_size,
    get_embed_model_id,
    get_inference_backend,
    inference_enabled,
    is_apple_silicon,
    resolve_backend,
)
from app.inference.embedder import Embedder, _sentence_available


def build_npu_preview_health() -> Dict[str, Any]:
    """Portfolio/demo payload: how the system presents when Core ML + Neural Engine is active."""
    model = get_embed_model_id()
    return {
        "enabled": True,
        "preview": True,
        "configured_backend": "coreml",
        "active_backend": "coreml",
        "model_id": f"coreml-{model}",
        "device_label": "Apple Neural Engine (Core ML)",
        "neural_engine": {
            "hardware_available": True,
            "active": True,
            "message": "Neural Engine path is active via Core ML embeddings.",
        },
        "sentence_transformers_installed": _sentence_available(),
        "chunk_size": get_chunk_size(),
        "chunk_overlap": get_chunk_overlap(),
        "embed_model_configured": model,
        "how_to_use": [
            "PREVIEW MODE — simulated NPU/Core ML status for UI demos.",
            "Upload a document — indexing uses Neural Engine embeddings.",
            "ask / review — hybrid search runs on-device with cited evidence.",
            "Set INFERENCE_BACKEND=coreml and add a Core ML bundle for real NPU indexing.",
        ],
        "user_facing_label": "Accelerated document search (Neural Engine path)",
    }


def build_inference_health(*, preview_npu: bool = False) -> Dict[str, Any]:
    if preview_npu:
        return build_npu_preview_health()

    configured = get_inference_backend()
    active = resolve_backend()
    embedder = Embedder.from_env()
    neural_active = active == "coreml" or embedder.device_label.startswith("Apple Neural")

    steps: List[str] = [
        "Upload a document at POST /documents/upload — semantic index builds in the background.",
        "Poll GET /documents/{id} until index_status is ready.",
        "Ask questions at POST /documents/{id}/ask — hybrid keyword + semantic citations.",
        "Open GET /inference/health anytime to see accelerator and model status.",
    ]

    if is_apple_silicon() and not neural_active:
        steps.append(
            "On Apple Silicon: install sentence-transformers for better CPU embeddings; "
            "Core ML / Neural Engine bundle export is the next step for INFERENCE_BACKEND=coreml."
        )

    return {
        "enabled": inference_enabled(),
        "configured_backend": configured,
        "active_backend": embedder.backend,
        "model_id": embedder.model_id,
        "device_label": embedder.device_label,
        "neural_engine": {
            "hardware_available": is_apple_silicon(),
            "active": neural_active,
            "message": _neural_message(embedder.backend, neural_active),
        },
        "sentence_transformers_installed": _sentence_available(),
        "chunk_size": get_chunk_size(),
        "chunk_overlap": get_chunk_overlap(),
        "embed_model_configured": get_embed_model_id(),
        "how_to_use": steps,
        "user_facing_label": _user_label(embedder),
    }


def _neural_message(active_backend: str, neural_active: bool) -> str:
    if neural_active:
        return "Neural Engine path is active via Core ML embeddings."
    if is_apple_silicon():
        if active_backend == "hash":
            return (
                "Apple Silicon detected. Running lightweight CPU hash index now. "
                "Install sentence-transformers or add a Core ML embed bundle for richer search."
            )
        return "Apple Silicon detected. Embeddings run on CPU until a Core ML model bundle is added."
    return "Neural Engine acceleration is available on Apple Silicon and Windows NPU devices; this host uses CPU indexing."


def _user_label(embedder: Embedder) -> str:
    if not inference_enabled():
        return "Semantic index disabled (INFERENCE_BACKEND=none)"
    if embedder.device_label.startswith("Apple"):
        return "Accelerated document search (Neural Engine path)"
    if embedder.backend == "sentence":
        return "Semantic document search (CPU, MiniLM embeddings)"
    return "Semantic document search (CPU, lightweight index)"
