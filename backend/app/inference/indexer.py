from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import delete, select

from app.inference.chunking import chunk_document
from app.inference.config import (
    get_chunk_overlap,
    get_chunk_size,
    inference_enabled,
)
from app.inference.embedder import Embedder, top_similar_chunks

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.main import Document, DocumentChunk, DocumentIndex

logger = logging.getLogger("evidenceos.inference")


def index_document(db: "Session", document: "Document") -> "DocumentIndex":
    from app.main import DocumentChunk, DocumentIndex

    index_row = db.get(DocumentIndex, document.id)
    if index_row is None:
        index_row = DocumentIndex(document_id=document.id)
        db.add(index_row)

    if not inference_enabled():
        index_row.status = "disabled"
        index_row.chunk_count = 0
        index_row.backend = "none"
        index_row.device_label = "disabled"
        index_row.model_id = "none"
        index_row.error = None
        index_row.updated_at = datetime.now(timezone.utc)
        db.flush()
        return index_row

    embedder = Embedder.from_env()
    index_row.status = "indexing"
    index_row.backend = embedder.backend
    index_row.device_label = embedder.device_label
    index_row.model_id = embedder.model_id
    index_row.error = None
    index_row.updated_at = datetime.now(timezone.utc)
    db.flush()

    try:
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        pieces = chunk_document(document.text, get_chunk_size(), get_chunk_overlap())
        if not pieces:
            raise ValueError("no chunks produced from document text")

        texts = [piece["text"] for piece in pieces]
        vectors = embedder.embed_texts(texts)

        for piece, vector in zip(pieces, vectors):
            db.add(
                DocumentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    chunk_index=piece["chunk_index"],
                    text=piece["text"],
                    char_start=piece["char_start"],
                    char_end=piece["char_end"],
                    embedding_json=json.dumps(vector),
                )
            )

        index_row.status = "ready"
        index_row.chunk_count = len(pieces)
        index_row.updated_at = datetime.now(timezone.utc)
        db.flush()
        logger.info(
            "indexed document %s with %s chunks via %s (%s)",
            document.id,
            len(pieces),
            embedder.backend,
            embedder.device_label,
        )
    except Exception as exc:
        index_row.status = "failed"
        index_row.error = str(exc)
        index_row.updated_at = datetime.now(timezone.utc)
        logger.exception("failed to index document %s", document.id)
        db.flush()

    return index_row


def semantic_citations(
    db: "Session",
    document: "Document",
    query: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    from app.main import DocumentChunk, DocumentIndex

    index_row = db.get(DocumentIndex, document.id)
    if index_row is None or index_row.status != "ready":
        return []

    rows = db.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index.asc())
    ).all()

    if not rows:
        return []

    embedder = Embedder.from_env()
    query_vector = embedder.embed_texts([query])[0]
    chunk_rows: List[tuple[str, List[float], str, int]] = []
    for row in rows:
        vector = json.loads(row.embedding_json)
        chunk_rows.append((row.id, vector, row.text, row.chunk_index))

    hits = top_similar_chunks(query_vector, chunk_rows, limit=limit)
    citations: List[Dict[str, Any]] = []

    for score, text, chunk_index in hits:
        citations.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "page": None,
                "chunk_index": chunk_index,
                "source_text": text[:800],
                "score": int(round(score * 100)),
                "verified": True,
                "retrieval": "semantic",
            }
        )

    return citations
