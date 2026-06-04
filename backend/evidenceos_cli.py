#!/usr/bin/env python3
"""Minimal CLI for EvidenceOS. Talks to the local FastAPI backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

API_BASE = os.getenv("EVIDENCEOS_API", "http://127.0.0.1:8000").rstrip("/")
STATE_FILE = Path(os.getenv("EVIDENCEOS_STATE", Path.home() / ".evidenceos" / "state.json"))


def load_doc_id() -> Optional[str]:
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("document_id")
    except Exception:
        return None


def save_doc_id(document_id: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"document_id": document_id}, indent=2),
        encoding="utf-8",
    )


def request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
) -> Any:
    with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
        response = client.request(method, path, json=json_body, files=files)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise SystemExit(f"error {response.status_code}: {detail}")
        if not response.content:
            return {}
        return response.json()


def print_health(health: Dict[str, Any], inference: Dict[str, Any]) -> None:
    neural = inference.get("neural_engine") or {}
    if inference.get("preview"):
        print("PREVIEW — simulated NPU / Neural Engine system")
        print()
    if neural.get("active"):
        print("━━━ Apple Neural Engine ━━━  ACTIVE")
        print()
    elif neural.get("hardware_available"):
        print("━━━ Apple Silicon ━━━  CPU index (NPU not active)")
        print()
    print(f"backend: {health.get('status')}")
    print(f"label: {inference.get('user_facing_label')}")
    print(f"device: {inference.get('device_label')}")
    print(f"index backend: {inference.get('active_backend')}")
    print(f"model: {inference.get('model_id')}")
    if neural.get("message"):
        print(f"note: {neural.get('message')}")


def cmd_health(preview_npu: bool = False) -> None:
    health = request("GET", "/health")
    path = "/inference/health?preview=npu" if preview_npu else "/inference/health"
    inference = request("GET", path)
    print_health(health, inference)


def cmd_upload(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"file not found: {path}")

    with path.open("rb") as handle:
        data = request(
            "POST",
            "/documents/upload",
            files={"file": (path.name, handle, "application/octet-stream")},
        )

    save_doc_id(data["id"])
    print(f"uploaded: {data['filename']}")
    print(f"doc: {data['id']}")
    print(f"index: {data['index_status']}  chunks: {data['chunk_count']}")


def cmd_ask(question: str, document_id: Optional[str]) -> None:
    doc_id = document_id or load_doc_id()
    if not doc_id:
        raise SystemExit("no document — run: evidenceos_cli.py upload <file>")

    data = request("POST", f"/documents/{doc_id}/ask", json_body={"question": question})
    print(f"mode: {data.get('retrieval_mode')}  confidence: {data.get('confidence')}%")
    print()
    print(data.get("answer", ""))
    citations = data.get("citations") or []
    if citations:
        print()
        print("citations:")
        for index, citation in enumerate(citations, start=1):
            snippet = (citation.get("source_text") or "")[:200]
            print(f"  [{index}] {snippet}")


def cmd_review(focus: str, document_id: Optional[str]) -> None:
    doc_id = document_id or load_doc_id()
    if not doc_id:
        raise SystemExit("no document — run: evidenceos_cli.py upload <file>")

    data = request(
        "POST",
        f"/documents/{doc_id}/review",
        json_body={"focus": focus},
    )
    print(data.get("summary", ""))
    for risk in data.get("risks") or []:
        print(f"  risk: {risk.get('risk')}")


def cmd_use(document_id: str) -> None:
    save_doc_id(document_id)
    print(f"active doc: {document_id}")


def cmd_smoke() -> None:
    for item in request("GET", "/evals/smoke"):
        mark = "ok" if item.get("passed") else "FAIL"
        print(f"{mark}  {item.get('name')}")


def repl() -> None:
    doc_id = load_doc_id()
    print("EvidenceOS CLI — commands: help | health | upload <path> | ask <q> | review | smoke | quit")
    if doc_id:
        print(f"active doc: {doc_id}")

    while True:
        try:
            raw = input("evidenceos> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if cmd in {"quit", "exit", "q"}:
            break
        if cmd in {"help", "?"}:
            print(
                "  health | health npu | upload <path> | use <id> | ask <question> | "
                "review [focus] | smoke | clear"
            )
            continue
        if cmd == "clear":
            print("\033[2J\033[H", end="")
            continue
        if cmd == "health":
            cmd_health(rest.strip().lower() == "npu")
        elif cmd == "upload":
            if not rest:
                print("usage: upload <path>")
            else:
                cmd_upload(Path(rest))
                doc_id = load_doc_id()
        elif cmd == "use":
            if not rest:
                print("usage: use <document-id>")
            else:
                cmd_use(rest.split()[0])
                doc_id = load_doc_id()
        elif cmd == "ask":
            if not rest:
                print("usage: ask <question>")
            else:
                cmd_ask(rest, doc_id)
        elif cmd == "review":
            cmd_review(rest or "risks, gaps, key facts, and missing evidence", doc_id)
        elif cmd == "smoke":
            cmd_smoke()
        else:
            print(f"unknown: {cmd}  (type help)")


def main() -> None:
    parser = argparse.ArgumentParser(description="EvidenceOS minimal CLI")
    parser.add_argument("--api", default=API_BASE, help="API base URL")
    sub = parser.add_subparsers(dest="command")

    health_p = sub.add_parser("health", help="backend and index status")
    health_p.add_argument(
        "--preview-npu",
        action="store_true",
        help="show simulated Neural Engine / Core ML status (demo)",
    )
    sub.add_parser("smoke", help="run smoke evals")

    upload_p = sub.add_parser("upload", help="upload a document")
    upload_p.add_argument("path", type=Path)

    ask_p = sub.add_parser("ask", help="ask about active document")
    ask_p.add_argument("question")
    ask_p.add_argument("--doc", dest="document_id", default=None)

    review_p = sub.add_parser("review", help="review active document")
    review_p.add_argument("focus", nargs="?", default="risks, gaps, key facts, and missing evidence")
    review_p.add_argument("--doc", dest="document_id", default=None)

    use_p = sub.add_parser("use", help="set active document id")
    use_p.add_argument("document_id")

    sub.add_parser("repl", help="interactive prompt")

    args = parser.parse_args()
    global API_BASE
    API_BASE = args.api.rstrip("/")

    if args.command is None:
        repl()
        return

    if args.command == "health":
        cmd_health(getattr(args, "preview_npu", False))
    elif args.command == "upload":
        cmd_upload(args.path)
    elif args.command == "ask":
        cmd_ask(args.question, args.document_id)
    elif args.command == "review":
        cmd_review(args.focus, args.document_id)
    elif args.command == "use":
        cmd_use(args.document_id)
    elif args.command == "smoke":
        cmd_smoke()
    elif args.command == "repl":
        repl()


if __name__ == "__main__":
    main()
