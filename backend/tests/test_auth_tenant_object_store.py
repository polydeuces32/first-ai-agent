from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("DEFAULT_TENANT_SLUG", "acme")
    monkeypatch.setenv("DEFAULT_TENANT_NAME", "Acme, Inc.")
    monkeypatch.setenv("DEFAULT_API_KEY", "test-api-key-acme")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "object-store"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./agentops.db")
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": "test-api-key-acme",
    }


def test_unauthorized_requests_are_rejected(client: TestClient) -> None:
    upload = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert upload.status_code == 401

    documents = client.get("/documents")
    assert documents.status_code == 401


def test_tenant_auth_identity_and_object_key(client: TestClient) -> None:
    me = client.get("/auth/me", headers=auth_headers())
    assert me.status_code == 200
    assert me.json()["tenant_slug"] == "acme"

    upload = client.post(
        "/documents/upload",
        headers=auth_headers(),
        files={"file": ("tenant_note.txt", io.BytesIO(b"tenant specific content"), "text/plain")},
    )
    assert upload.status_code == 200
    payload = upload.json()
    assert payload["tenant_slug"] == "acme"
    assert payload["object_key"].startswith("tenants/acme/documents/")

    listed = client.get("/documents", headers=auth_headers())
    assert listed.status_code == 200
    documents = listed.json()
    assert len(documents) >= 1
    assert documents[0]["tenant_slug"] == "acme"
    assert documents[0]["filename"] == "tenant_note.txt"


def test_tenant_scoped_answers_are_isolated(client: TestClient) -> None:
    upload = client.post(
        "/documents/upload",
        headers=auth_headers(),
        files={"file": ("tenant_note.txt", io.BytesIO(b"This tenant has one private note."), "text/plain")},
    )
    document_id = upload.json()["id"]

    ask = client.post(
        f"/documents/{document_id}/ask",
        headers=auth_headers(),
        json={"question": "What does the note say?"},
    )
    assert ask.status_code == 200
    answer = ask.json()
    assert answer["tenant_slug"] == "acme"
    assert answer["abstained"] is False


def test_metrics_endpoint_exposes_request_and_auth_counters(client: TestClient) -> None:
    client.get("/health")
    client.get("/ready")
    client.get("/metrics")

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    assert "http_requests_total" in body
    assert "auth_failures_total" in body
    assert "document_uploads_total" in body
