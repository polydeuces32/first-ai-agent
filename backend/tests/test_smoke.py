from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_ready_demo_and_tools() -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "first-ai-agent"}

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}

    demo = client.get("/demo")
    assert demo.status_code == 200
    payload = demo.json()
    assert payload["product"] == "EvidenceOS"
    assert "upload a txt, md, csv, or pdf document" in " ".join(payload["demo_flow"]).lower()

    tools = client.get("/tools")
    assert tools.status_code == 200
    tool_names = {tool["name"] for tool in tools.json()}
    assert tool_names == {"answer", "write_report"}

    smoke = client.get("/evals/smoke")
    assert smoke.status_code == 200
    assert all(item["passed"] for item in smoke.json())


def test_document_upload_ask_and_guardrail() -> None:
    doc_text = (
        "Agent Sentinel is a local control center for system health, local workflows, and safe actions. "
        "This document explains setup, architecture, and operational notes for the project."
    )

    upload = client.post(
        "/documents/upload",
        files={"file": ("sentinel_notes.txt", io.BytesIO(doc_text.encode("utf-8")), "text/plain")},
    )
    assert upload.status_code == 200
    document = upload.json()
    assert document["filename"] == "sentinel_notes.txt"
    assert document["text_length"] > 0
    assert document["page_count"] == 1

    document_id = document["id"]

    ask = client.post(
        f"/documents/{document_id}/ask",
        json={"question": "What does the document explain?"},
    )
    assert ask.status_code == 200
    answer = ask.json()
    assert answer["document_id"] == document_id
    assert answer["abstained"] is False
    assert answer["citations"]
    assert answer["confidence"] > 0

    review = client.post(
        f"/documents/{document_id}/review",
        json={"focus": "contract terms"},
    )
    assert review.status_code == 200
    review_payload = review.json()
    assert review_payload["document_id"] == document_id
    assert review_payload["approval_required"] is False
    assert review_payload["risks"] == []
    assert review_payload["citations"] == []
