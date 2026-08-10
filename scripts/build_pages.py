from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
FILES = [
    "index.html",
    "evidenceos.html",
]


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)

    for name in FILES:
        source = ROOT / name
        target = DIST / name
        if not source.exists():
            raise FileNotFoundError(f"missing static asset: {source}")
        shutil.copy2(source, target)


if __name__ == "__main__":
    main()
