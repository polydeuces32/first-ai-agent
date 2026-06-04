from __future__ import annotations

from typing import Any, Dict, List


def chunk_document(text: str, size: int, overlap: int) -> List[Dict[str, Any]]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    chunks: List[Dict[str, Any]] = []
    start = 0
    index = 0
    length = len(normalized)
    step = max(1, size - overlap)

    while start < length:
        end = min(length, start + size)
        piece = normalized[start:end].strip()
        if piece:
            chunks.append(
                {
                    "chunk_index": index,
                    "text": piece,
                    "char_start": start,
                    "char_end": end,
                }
            )
            index += 1
        if end >= length:
            break
        start += step

    return chunks
