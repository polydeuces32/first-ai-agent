#!/usr/bin/env python3
"""Local document intelligence helpers for First AI Agent.

Creates lightweight summaries and metadata from extracted PDF text or OCR sidecar files.
No cloud calls. No API keys.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "you", "your", "are", "was", "were",
    "have", "has", "had", "not", "but", "can", "will", "would", "should", "could", "about",
    "into", "than", "then", "they", "them", "their", "there", "what", "when", "where", "which",
    "also", "only", "been", "more", "most", "some", "such", "each", "page", "pages"
}

DOC_TYPE_RULES = [
    ("receipt", ["subtotal", "total", "tax", "cash", "visa", "mastercard", "receipt", "change"]),
    ("invoice", ["invoice", "amount due", "bill to", "payment terms", "due date"]),
    ("contract", ["agreement", "terms", "party", "parties", "liability", "termination", "signature"]),
    ("class notes", ["chapter", "lecture", "notes", "assignment", "homework", "professor"]),
    ("resume", ["experience", "education", "skills", "projects", "employment"]),
    ("letter", ["dear", "sincerely", "regards", "to whom it may concern"]),
]


def load_text_for_document(path: str) -> str:
    doc = Path(path)
    sidecar = Path(str(doc) + ".ocr.txt")
    if sidecar.exists():
        return sidecar.read_text(encoding="utf-8", errors="ignore")
    if doc.suffix.lower() in {".txt", ".md", ".markdown"}:
        return doc.read_text(encoding="utf-8", errors="ignore")
    return ""


def split_sentences(text: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if len(p.strip()) > 25]


def extract_keywords(text: str, limit: int = 12) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return [w for w, _ in Counter(words).most_common(limit)]


def classify_document(text: str) -> str:
    lower = text.lower()
    scores = []
    for label, terms in DOC_TYPE_RULES:
        score = sum(1 for t in terms if t in lower)
        if score:
            scores.append((score, label))
    if not scores:
        return "general document"
    scores.sort(reverse=True)
    return scores[0][1]


def summarize_text(text: str, max_sentences: int = 5) -> List[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    keywords = set(extract_keywords(text, 20))
    scored = []
    for idx, sentence in enumerate(sentences[:80]):
        s_lower = sentence.lower()
        score = sum(1 for k in keywords if k in s_lower)
        if idx < 5:
            score += 1
        scored.append((score, idx, sentence))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = sorted(scored[:max_sentences], key=lambda x: x[1])
    return [s for _, _, s in picked]


def build_document_card(path: str) -> Dict[str, Any]:
    doc = Path(path)
    text = load_text_for_document(path)
    keywords = extract_keywords(text) if text else []
    summary = summarize_text(text) if text else []
    return {
        "filename": doc.name,
        "path": str(doc),
        "type": classify_document(text) if text else "image/scanned document",
        "keywords": keywords,
        "summary": summary,
        "text_chars": len(text),
        "has_text": bool(text.strip()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def save_document_card(path: str) -> Dict[str, Any]:
    card = build_document_card(path)
    out = Path(path).with_suffix(Path(path).suffix + ".json")
    out.write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card
