#!/usr/bin/env python3
"""Release readiness gate for EvidenceOS growth / App Store confidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV_PY = BACKEND / ".venv" / "bin" / "python"
PYTHON = str(VENV_PY if VENV_PY.exists() else "python3")


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    FAILURES.append(msg)


FAILURES: list[str] = []


def check_files() -> None:
    print("Files")
    required = [
        ROOT / "GROWTH.md",
        ROOT / "render.yaml",
        ROOT / "Dockerfile",
        ROOT / "store" / "app-store-metadata.json",
        ROOT / "ios" / "README.md",
        ROOT / "ios" / "EvidenceOS" / "EvidenceOSApp.swift",
        ROOT / "ios" / "EvidenceOS" / "ContentView.swift",
        ROOT / "backend" / "app" / "pages" / "legal.py",
        ROOT / "docs" / "app-store" / "CHECKLIST.md",
        ROOT / "docs" / "growth" / "ROADMAP.md",
    ]
    for path in required:
        if path.exists():
            ok(str(path.relative_to(ROOT)))
        else:
            fail(f"missing {path.relative_to(ROOT)}")


def check_routes() -> None:
    print("Routes")
    import subprocess

    code = """
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./readiness_routes.db")
from fastapi.testclient import TestClient
from app.main import app, init_db
init_db()
c = TestClient(app)
paths = ["/privacy", "/support", "/terms", "/health-disclaimer", "/app", "/try"]
failed = []
for path in paths:
    status = c.get(path).status_code
    print(f"{path}\\t{status}")
    if status != 200:
        failed.append(path)
raise SystemExit(1 if failed else 0)
"""
    proc = subprocess.run(
        [PYTHON, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    (BACKEND / "readiness_routes.db").unlink(missing_ok=True)
    for line in proc.stdout.strip().splitlines():
        path, status = line.split("\t")
        if status == "200":
            ok(f"GET {path} -> 200")
        else:
            fail(f"GET {path} -> {status}")
    if proc.returncode != 0 and not proc.stdout.strip():
        fail(f"route check failed: {proc.stderr[-300:]}")


def check_tests() -> None:
    print("Tests")
    import subprocess

    proc = subprocess.run(
        [PYTHON, "-m", "pytest", "-q"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env={"DATABASE_URL": "sqlite:///./readiness_test.db", **dict(__import__("os").environ)},
    )
    (BACKEND / "readiness_test.db").unlink(missing_ok=True)
    if proc.returncode == 0:
        ok("backend tests pass")
    else:
        fail("backend tests failed")
        print(proc.stdout[-500:])
        print(proc.stderr[-500:])


def check_metadata() -> None:
    print("App Store metadata")
    meta = json.loads((ROOT / "store" / "app-store-metadata.json").read_text())
    for key in ["privacy_policy_url", "support_url", "description", "review_notes"]:
        if meta.get(key):
            ok(key)
        else:
            fail(f"app-store-metadata.json missing {key}")


def main() -> int:
    print("EvidenceOS release readiness\n")
    check_files()
    check_routes()
    check_metadata()
    check_tests()
    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)} issue(s))")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("READY — structural gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
