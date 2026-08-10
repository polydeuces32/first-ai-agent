from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def hash_inference_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFERENCE_BACKEND", "hash")


client = TestClient(app)


def test_inference_health_npu_preview() -> None:
    response = client.get("/inference/health?preview=npu")
    assert response.status_code == 200
    payload = response.json()
    assert payload["preview"] is True
    assert payload["active_backend"] == "coreml"
    assert payload["neural_engine"]["active"] is True
    assert "Neural Engine" in payload["device_label"]


def test_inference_health_exposes_user_steps() -> None:
    response = client.get("/inference/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["active_backend"] == "hash"
    assert payload["user_facing_label"]
    assert payload["how_to_use"]
    assert "neural_engine" in payload


def test_upload_indexes_document_for_semantic_search() -> None:
    text = (
        "Payment terms require net thirty settlement. "
        "Auto-renewal applies unless terminated with thirty days written notice. "
        "Liability is capped at fees paid in the prior twelve months."
    )

    upload = client.post(
        "/documents/upload",
        files={"file": ("terms.txt", io.BytesIO(text.encode("utf-8")), "text/plain")},
    )
    assert upload.status_code == 200
    document = upload.json()
    assert document["index_status"] == "ready"
    assert document["chunk_count"] >= 1
    assert document["semantic_search_ready"] is True
    assert document["index_device"]

    ask = client.post(
        f"/documents/{document['id']}/ask",
        json={"question": "What are the payment terms?"},
    )
    assert ask.status_code == 200
    answer = ask.json()
    assert answer["retrieval_mode"] in {"hybrid", "keyword"}
    assert answer["citations"]


def test_reindex_endpoint() -> None:
    text = "Termination requires written notice within thirty days of breach."

    upload = client.post(
        "/documents/upload",
        files={"file": ("clause.txt", io.BytesIO(text.encode("utf-8")), "text/plain")},
    )
    document_id = upload.json()["id"]

    reindex = client.post(f"/documents/{document_id}/reindex")
    assert reindex.status_code == 200
    assert reindex.json()["index_status"] == "ready"


def test_documents_endpoint_returns_recent_documents() -> None:
    first = client.post(
        "/documents/upload",
        files={"file": ("recent_one.txt", io.BytesIO(b"First recent document."), "text/plain")},
    )
    assert first.status_code == 200

    second = client.post(
        "/documents/upload",
        files={"file": ("recent_two.txt", io.BytesIO(b"Second recent document."), "text/plain")},
    )
    assert second.status_code == 200

    response = client.get("/documents")
    assert response.status_code == 200
    documents = response.json()
    filenames = [document["filename"] for document in documents]
    assert "recent_two.txt" in filenames
    assert "recent_one.txt" in filenames
    assert documents[0]["filename"] == "recent_two.txt"
    assert documents[1]["filename"] == "recent_one.txt"
