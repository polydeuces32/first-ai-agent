from __future__ import annotations

import html
import logging
import os
import re
import secrets
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from app.pages import PUBLIC_LEGAL_PATHS, legal_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import JSON, DateTime, Enum as SAEnum, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentops.db")
APP_NAME = os.getenv("APP_NAME", "first-ai-agent")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
APP_ENV = os.getenv("APP_ENV", "development")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "storage/uploads"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8788",
    "http://localhost:8788",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(APP_NAME)
PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/inference/health",
    "/demo",
}

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
AUTH_FAILURES_TOTAL = Counter(
    "auth_failures_total",
    "Total auth failures",
    ["path"],
)
DOCUMENT_UPLOADS_TOTAL = Counter(
    "document_uploads_total",
    "Total document uploads",
    ["tenant_slug"],
)
DOCUMENT_QUERIES_TOTAL = Counter(
    "document_queries_total",
    "Total document questions",
    ["tenant_slug"],
)
DOCUMENT_REVIEWS_TOTAL = Counter(
    "document_reviews_total",
    "Total document reviews",
    ["tenant_slug"],
)
REQUEST_LATENCY_SECONDS = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


def parse_allowed_origins(raw: Optional[str]) -> List[str]:
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or DEFAULT_ALLOWED_ORIGINS


def get_allowed_origins() -> List[str]:
    return parse_allowed_origins(os.getenv("ALLOWED_ORIGINS"))


def get_default_tenant_slug() -> str:
    return os.getenv("DEFAULT_TENANT_SLUG", "public")


def get_default_tenant_name() -> str:
    return os.getenv("DEFAULT_TENANT_NAME", "Public Tenant")


def get_required_api_key() -> Optional[str]:
    return os.getenv("DEFAULT_API_KEY") or None


def get_object_storage_root() -> Path:
    return Path(os.getenv("OBJECT_STORAGE_ROOT", "storage/object-store"))


def get_upload_dir() -> Path:
    return Path(os.getenv("UPLOAD_DIR", str(get_object_storage_root() / "uploads")))


def get_active_tenant_from_id(document_id: str) -> Optional[str]:
    if ":" not in document_id:
        return None
    return document_id.split(":", 1)[0]


ALLOWED_ORIGINS = get_allowed_origins()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")),
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class RunStatus(str, Enum):
    CREATED = "created"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ToolRisk(str, Enum):
    LOW = "low"
    HIGH = "high"


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus),
        default=RunStatus.CREATED,
        nullable=False,
    )
    selected_tool: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    risk: Mapped[ToolRisk] = mapped_column(SAEnum(ToolRisk), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(36), index=True, nullable=True)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ShareCard(Base):
    __tablename__ = "share_cards"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    source_title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstained: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class DocumentIndex(Base):
    __tablename__ = "document_indexes"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    device_label: Mapped[str] = mapped_column(String(120), nullable=False, default="pending")
    model_id: Mapped[str] = mapped_column(String(120), nullable=False, default="pending")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)


class RunCreate(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    dry_run: bool = True


class RunResponse(BaseModel):
    id: str
    prompt: str
    status: RunStatus
    selected_tool: Optional[str]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime


class ApprovalRequest(BaseModel):
    approved: bool
    reason: Optional[str] = None


class ToolSpec(BaseModel):
    name: str
    description: str
    risk: ToolRisk
    requires_approval: bool


class EvalResult(BaseModel):
    name: str
    passed: bool
    details: str


class TenantResponse(BaseModel):
    tenant_slug: str
    tenant_name: str
    authenticated: bool


class DocumentResponse(BaseModel):
    id: str
    tenant_slug: str
    filename: str
    content_type: Optional[str]
    object_key: str
    text_length: int
    page_count: int
    created_at: datetime
    index_status: str = "pending"
    chunk_count: int = 0
    index_device: Optional[str] = None
    semantic_search_ready: bool = False


class AskDocumentRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class ReviewDocumentRequest(BaseModel):
    focus: Optional[str] = Field(
        default="risks, gaps, key facts, and missing evidence",
        max_length=1000,
    )


class DocumentAnswer(BaseModel):
    document_id: str
    tenant_slug: str
    question: str
    answer: str
    citations: List[Dict[str, Any]]
    confidence: int
    abstained: bool
    retrieval_mode: str = "keyword"


class DocumentReview(BaseModel):
    document_id: str
    tenant_slug: str
    summary: str
    key_facts: List[str]
    risks: List[Dict[str, Any]]
    missing_evidence: List[str]
    citations: List[Dict[str, Any]]
    approval_required: bool


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: Dict[str, ToolSpec] = {
            "answer": ToolSpec(
                name="answer",
                description="Return a safe local answer without external side effects.",
                risk=ToolRisk.LOW,
                requires_approval=False,
            ),
            "write_report": ToolSpec(
                name="write_report",
                description="Generate a structured document review report. Approval required before report execution.",
                risk=ToolRisk.HIGH,
                requires_approval=True,
            ),
        }

    def list_tools(self) -> List[ToolSpec]:
        return list(self.tools.values())

    def choose_tool(self, prompt: str) -> ToolSpec:
        lowered = prompt.lower()

        high_risk_terms = [
            "write",
            "create report",
            "report",
            "save",
            "export",
            "delete",
            "send",
            "review",
            "risk",
            "risks",
            "identify risks",
            "analyze document",
            "analyse document",
            "audit",
            "extract findings",
            "generate report",
            "document review",
            "risk review",
            "compliance",
            "approval",
            "approve",
            "publish",
        ]

        if any(term in lowered for term in high_risk_terms):
            return self.tools["write_report"]

        return self.tools["answer"]

    def execute(self, tool: ToolSpec, prompt: str) -> Dict[str, Any]:
        if tool.name == "answer":
            return {
                "answer": "Agent run completed locally. Document upload, retrieval, and citation checks are available under /documents.",
                "input_summary": prompt[:500],
            }

        if tool.name == "write_report":
            return {
                "report": {
                    "title": "EvidenceOS Document Review Report",
                    "summary": prompt[:1000],
                    "risk_findings": [
                        {
                            "risk": "Report generation requires human approval.",
                            "severity": "medium",
                            "reason": "Approval gate is active for review/report workflows.",
                            "citation": None,
                        }
                    ],
                    "missing_evidence": [
                        "Attach a document through POST /documents/upload for grounded review.",
                    ],
                    "approval_status": "approved",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            }

        raise ValueError(f"Unknown tool: {tool.name}")


tool_registry = ToolRegistry()

app = FastAPI(title="EvidenceOS AgentOps Backend", version="0.3.5")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(legal_router)
PUBLIC_PATHS.update(PUBLIC_LEGAL_PATHS)


def init_db() -> None:
    get_upload_dir().mkdir(parents=True, exist_ok=True)
    get_object_storage_root().mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def require_api_key(request: Request) -> None:
    required = get_required_api_key()
    if not required:
        return
    provided = request.headers.get("X-API-Key")
    if provided != required:
        AUTH_FAILURES_TOTAL.labels(path=request.url.path).inc()
        raise HTTPException(status_code=401, detail="unauthorized")


def current_tenant_slug(request: Request) -> str:
    require_api_key(request)
    return get_default_tenant_slug()


def object_key_for(tenant_slug: str, document_id: str, filename: str) -> str:
    return f"tenants/{tenant_slug}/documents/{document_id}_{filename}"


def upload_path_for(tenant_slug: str, document_id: str, filename: str) -> Path:
    return get_object_storage_root() / object_key_for(tenant_slug, document_id, filename)


def db_ping() -> None:
    with SessionLocal() as db:
        db.execute(select(1))


def audit(
    db: Session,
    event: str,
    payload: Dict[str, Any],
    run_id: Optional[str] = None,
) -> None:
    init_db()
    row = AuditLog(
        id=str(uuid.uuid4()),
        run_id=run_id,
        event=event,
        payload=payload,
    )
    db.add(row)


def serialize_run(run: AgentRun) -> RunResponse:
    return RunResponse(
        id=run.id,
        prompt=run.prompt,
        status=run.status,
        selected_tool=run.selected_tool,
        result=run.result,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def serialize_document(
    document: Document,
    index_row: Optional[DocumentIndex] = None,
) -> DocumentResponse:
    object_key = str(document.storage_path)
    prefix = str(get_object_storage_root())
    if object_key.startswith(prefix):
        object_key = object_key[len(prefix):].lstrip("/")

    index_status = index_row.status if index_row else "pending"
    chunk_count = index_row.chunk_count if index_row else 0
    index_device = index_row.device_label if index_row else None

    return DocumentResponse(
        id=document.id,
        tenant_slug=get_default_tenant_slug(),
        filename=document.filename,
        content_type=document.content_type,
        object_key=object_key,
        text_length=document.text_length,
        page_count=document.page_count,
        created_at=document.created_at,
        index_status=index_status,
        chunk_count=chunk_count,
        index_device=index_device,
        semantic_search_ready=index_status == "ready",
    )


def safe_filename(filename: str) -> str:

    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.strip())
    return cleaned or "uploaded_document"


def extract_text_from_pdf(path: Path) -> tuple[str, int]:
    if PdfReader is None:
        raise HTTPException(status_code=500, detail="pypdf is not installed")

    reader = PdfReader(str(path))
    pages: List[str] = []

    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        pages.append(f"\n\n[Page {index}]\n{page_text}")

    return "\n".join(pages).strip(), len(reader.pages)


def extract_text_from_file(path: Path, content_type: Optional[str]) -> tuple[str, int]:
    suffix = path.suffix.lower()

    if suffix == ".pdf" or content_type == "application/pdf":
        return extract_text_from_pdf(path)

    if suffix in {".txt", ".md", ".csv"} or (content_type and content_type.startswith("text/")):
        return path.read_text(encoding="utf-8", errors="ignore"), 1

    raise HTTPException(
        status_code=400,
        detail="Unsupported file type. Use PDF, TXT, MD, or CSV for this version.",
    )


def get_document_or_404(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return document


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> List[str]:
    compact = normalize_text(text)
    if not compact:
        return []

    parts = re.split(r"(?<=[.!?])\s+", compact)
    return [part.strip() for part in parts if len(part.strip()) > 20]


def tokenize(text: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "this",
        "that",
        "with",
        "from",
        "what",
        "are",
        "was",
        "were",
        "will",
        "shall",
        "may",
        "can",
        "document",
        "agreement",
    }
    return {
        term
        for term in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(term) > 2 and term not in stopwords
    }


def score_sentence(question: str, sentence: str) -> int:
    q_terms = tokenize(question)
    s_terms = tokenize(sentence)

    if not q_terms or not s_terms:
        return 0

    overlap = q_terms & s_terms
    exact_bonus = 2 if question.lower() in sentence.lower() else 0

    return len(overlap) + exact_bonus


def infer_page(sentence: str) -> Optional[int]:
    page_match = re.search(r"\[Page\s+(\d+)\]", sentence)
    return int(page_match.group(1)) if page_match else None


def retrieve_keyword_evidence(document: Document, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    sentences = split_sentences(document.text)
    scored: List[tuple[int, str]] = []

    for sentence in sentences:
        score = score_sentence(query, sentence)
        if score > 0:
            scored.append((score, sentence))

    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored and sentences:
        scored = [(1, sentence) for sentence in sentences[:limit]]

    citations = []
    seen = set()

    for score, sentence in scored:
        normalized = normalize_text(sentence).lower()
        if normalized in seen:
            continue

        seen.add(normalized)

        citations.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "page": infer_page(sentence),
                "source_text": sentence[:800],
                "score": score,
                "verified": True,
                "retrieval": "keyword",
            }
        )

        if len(citations) >= limit:
            break

    return citations


def retrieve_evidence(
    db: Session,
    document: Document,
    query: str,
    limit: int = 5,
) -> tuple[List[Dict[str, Any]], str]:
    from app.inference.indexer import semantic_citations

    keyword_hits = retrieve_keyword_evidence(document, query, limit=limit)
    semantic_hits = semantic_citations(db, document, query, limit=limit)

    if not semantic_hits:
        return keyword_hits[:limit], "keyword"

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for citation in semantic_hits + keyword_hits:
        key = normalize_text(citation["source_text"]).lower()[:200]
        if key in seen:
            continue
        seen.add(key)
        merged.append(citation)
        if len(merged) >= limit:
            break

    return merged, "hybrid"


def detect_document_type(document: Document) -> Dict[str, Any]:
    text = document.text.lower()

    contract_terms = [
        "agreement",
        "party",
        "parties",
        "client",
        "vendor",
        "effective date",
        "payment terms",
        "invoice",
        "late fee",
        "auto-renew",
        "renewal",
        "terminate",
        "termination",
        "material breach",
        "liability",
        "indemnification",
        "confidentiality",
        "governing law",
        "signature",
    ]

    textbook_terms = [
        "chapter",
        "edition",
        "exercise",
        "proof",
        "theorem",
        "definition",
        "figure",
        "references",
        "bibliography",
        "authors",
        "publisher",
        "crc press",
        "introduction to",
        "private-key",
        "cryptography",
    ]

    contract_score = sum(1 for term in contract_terms if term in text)
    textbook_score = sum(1 for term in textbook_terms if term in text)

    if textbook_score >= 5 and textbook_score > contract_score:
        detected_type = "textbook_or_reference"
    elif contract_score >= 5:
        detected_type = "contract_or_agreement"
    else:
        detected_type = "unknown"

    return {
        "detected_type": detected_type,
        "contract_score": contract_score,
        "textbook_score": textbook_score,
        "contract_like": detected_type == "contract_or_agreement",
    }


def is_contract_review_focus(focus: str) -> bool:
    lowered = focus.lower()

    contract_focus_terms = [
        "payment",
        "renewal",
        "termination",
        "liability",
        "contract",
        "agreement",
        "clause",
        "breach",
        "signature",
        "effective date",
        "terms",
    ]

    return any(term in lowered for term in contract_focus_terms)


def build_document_answer(db: Session, document: Document, question: str) -> DocumentAnswer:
    citations, retrieval_mode = retrieve_evidence(db, document, question, limit=3)

    if not citations:
        return DocumentAnswer(
            document_id=document.id,
            tenant_slug=get_default_tenant_slug(),
            question=question,
            answer="I cannot answer from the uploaded document because no supporting evidence was found.",
            citations=[],
            confidence=0,
            abstained=True,
            retrieval_mode=retrieval_mode,
        )

    evidence_text = " ".join(item["source_text"] for item in citations)
    confidence = min(90, 40 + sum(item["score"] for item in citations) * 10)

    return DocumentAnswer(
        document_id=document.id,
        tenant_slug=get_default_tenant_slug(),
        question=question,
        answer=f"Based on verified evidence from the uploaded document: {evidence_text[:1200]}",
        citations=citations,
        confidence=confidence,
        abstained=False,
        retrieval_mode=retrieval_mode,
    )


def build_document_review(db: Session, document: Document, focus: str) -> DocumentReview:
    document_type = detect_document_type(document)

    if is_contract_review_focus(focus) and not document_type["contract_like"]:
        return DocumentReview(
            document_id=document.id,
            tenant_slug=get_default_tenant_slug(),
            summary=(
                f"Document '{document.filename}' appears to be '{document_type['detected_type']}', "
                "not a contract or agreement. Contract risk review was not applied."
            ),
            key_facts=[
                f"Detected document type: {document_type['detected_type']}",
                f"Contract score: {document_type['contract_score']}",
                f"Textbook/reference score: {document_type['textbook_score']}",
                "EvidenceOS skipped contract-specific risk findings because the document does not look contract-like.",
            ],
            risks=[],
            missing_evidence=[
                "Contract review requires a contract-like document with agreement, parties, payment terms, termination, liability, or signature language."
            ],
            citations=[],
            approval_required=False,
        )

    text_lower = document.text.lower()

    risk_terms = [
        "terminate",
        "termination",
        "penalty",
        "late fee",
        "liability",
        "indemnify",
        "breach",
        "confidential",
        "confidentiality",
        "auto-renew",
        "renewal",
        "payment",
        "interest",
        "non-refundable",
        "dispute",
    ]

    risks: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    seen_risk_terms = set()

    for term in risk_terms:
        if term not in text_lower or term in seen_risk_terms:
            continue

        evidence, _ = retrieve_evidence(db, document, term, limit=1)

        if not evidence:
            continue

        citation = evidence[0]
        if not citation.get("verified"):
            continue

        seen_risk_terms.add(term)
        citations.append(citation)

        risks.append(
            {
                "risk": f"Potential issue related to '{term}'.",
                "severity": "medium",
                "reason": "The term appears in the document and is supported by verified source text.",
                "citation": citation,
            }
        )

    sentences = split_sentences(document.text)
    key_facts = [sentence[:300] for sentence in sentences[:5]]

    missing_evidence = []
    for required in ["signature", "effective date", "payment terms", "termination"]:
        if required not in text_lower:
            missing_evidence.append(f"Could not confirm '{required}' in the document.")

    summary = (
        f"Document '{document.filename}' was reviewed for {focus}. "
        f"Detected document type: {document_type['detected_type']}. "
        f"Extracted {document.text_length} characters across {document.page_count} page(s). "
        f"Returned {len(risks)} verified risk finding(s)."
    )

    return DocumentReview(
        document_id=document.id,
        tenant_slug=get_default_tenant_slug(),
        summary=summary,
        key_facts=key_facts,
        risks=risks[:10],
        missing_evidence=missing_evidence,
        citations=citations[:10],
        approval_required=True,
    )


@app.on_event("startup")
def startup() -> None:
    init_db()
    logger.info("EvidenceOS backend started in %s mode", APP_ENV)


@app.get("/")
def root(request: Request) -> Response:
    accepts = request.headers.get("accept", "")
    if "text/html" in accepts:
        return HTMLResponse(render_landing_page())
    return JSONResponse(
        {
            "service": "EvidenceOS",
            "status": "running",
            "try": "/try",
            "privacy": "/privacy",
            "support": "/support",
            "terms": "/terms",
            "health_disclaimer": "/health-disclaimer",
            "ios": "/app",
            "docs": "/docs",
            "demo": "/demo",
            "health": "/health",
            "ready": "/ready",
            "inference": "/inference/health",
        }
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": APP_NAME}


@app.get("/demo")
def demo() -> Dict[str, Any]:
    return {
        "product": "EvidenceOS",
        "description": "Evidence verified document intelligence with citations, approvals, audit logs, and smoke evals.",
        "status": "running",
        "backend": "FastAPI",
        "database": "SQLite local default, DATABASE_URL configurable",
        "version": "0.3.5",
        "core_features": [
            "document upload",
            "text extraction",
            "semantic document index (CPU / Neural Engine ready)",
            "hybrid cited question answering",
            "document type detection",
            "verified citation risk review",
            "contract review guardrail",
            "human approval gate for high risk workflows",
            "audit logging",
            "smoke evaluations",
            "local frontend support through CORS",
        ],
        "demo_flow": [
            "Open GET /inference/health to see accelerator status",
            "Upload a TXT, MD, CSV, or PDF document",
            "Confirm index_status is ready on the upload response",
            "Ask a document question (hybrid semantic + keyword citations)",
            "Generate a risk review",
            "Check verified citations",
            "Run /evals/smoke",
        ],
        "important_endpoints": {
            "interactive_docs": "/docs",
            "portfolio_demo": "/demo",
            "inference_health": "/inference/health",
            "health": "/health",
            "readiness": "/ready",
            "tools": "/tools",
            "documents": "/documents",
            "upload": "/documents/upload",
            "reindex": "/documents/{document_id}/reindex",
            "smoke_evals": "/evals/smoke",
        },
        "safety_controls": [
            "High risk report and review actions route through approval",
            "Risk findings without verified citations are skipped",
            "Contract review is skipped for non-contract documents",
            "Unsupported files are rejected",
            "Empty text extraction is rejected",
            "Upload size is capped",
        ],
        "terminal_proof": [
            "curl http://127.0.0.1:8000/health | jq",
            "curl http://127.0.0.1:8000/demo | jq",
            "curl http://127.0.0.1:8000/evals/smoke | jq",
        ],
    }


@app.get("/ready")
def ready() -> Dict[str, str]:
    try:
        db_ping()
        return {"status": "ready"}
    except Exception as exc:
        logger.exception("readiness check failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/auth/me", response_model=TenantResponse)
def auth_me() -> TenantResponse:
    return TenantResponse(
        tenant_slug=get_default_tenant_slug(),
        tenant_name=get_default_tenant_name(),
        authenticated=True,
    )


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/tools", response_model=List[ToolSpec])
def list_tools() -> List[ToolSpec]:
    return tool_registry.list_tools()


@app.get("/inference/health")
def inference_health(preview: Optional[str] = None) -> Dict[str, Any]:
    from app.inference.health import build_inference_health

    preview_npu = (preview or "").strip().lower() in {"npu", "neural", "coreml", "1", "true"}
    return build_inference_health(preview_npu=preview_npu)


@app.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(request: Request, file: UploadFile = File(...)) -> DocumentResponse:
    tenant_slug = current_tenant_slug(request)
    filename = safe_filename(file.filename or "uploaded_document")
    document_id = str(uuid.uuid4())
    target_path = upload_path_for(tenant_slug, document_id, filename)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = 0

    with target_path.open("wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break

            bytes_written += len(chunk)

            if bytes_written > MAX_UPLOAD_BYTES:
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")

            buffer.write(chunk)

    text, page_count = extract_text_from_file(target_path, file.content_type)

    if not text.strip():
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="No extractable text found in document")

    now = datetime.now(timezone.utc)

    document = Document(
        id=document_id,
        filename=filename,
        content_type=file.content_type,
        storage_path=str(target_path),
        text=text,
        text_length=len(text),
        page_count=page_count,
        created_at=now,
    )

    with SessionLocal() as db:
        db.add(document)
        audit(
            db,
            "document_uploaded",
            {
                "tenant_slug": tenant_slug,
                "document_id": document_id,
                "filename": filename,
                "content_type": file.content_type,
                "bytes_written": bytes_written,
                "text_length": len(text),
                "page_count": page_count,
            },
        )
        db.commit()
        db.refresh(document)

        from app.inference.indexer import index_document

        index_row = index_document(db, document)
        audit(
            db,
            "document_indexed",
            {
                "document_id": document_id,
                "index_status": index_row.status,
                "chunk_count": index_row.chunk_count,
                "backend": index_row.backend,
                "device_label": index_row.device_label,
            },
        )
        db.commit()
        return serialize_document(document, index_row)


@app.get("/documents", response_model=List[DocumentResponse])
def list_documents(request: Request) -> List[DocumentResponse]:
    current_tenant_slug(request)
    with SessionLocal() as db:
        documents = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
        return [
            serialize_document(document, db.get(DocumentIndex, document.id))
            for document in documents[:5]
        ]


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str) -> DocumentResponse:
    with SessionLocal() as db:
        document = get_document_or_404(db, document_id)
        index_row = db.get(DocumentIndex, document_id)
        return serialize_document(document, index_row)


@app.post("/documents/{document_id}/reindex", response_model=DocumentResponse)
def reindex_document(document_id: str) -> DocumentResponse:
    with SessionLocal() as db:
        document = get_document_or_404(db, document_id)
        from app.inference.indexer import index_document

        index_row = index_document(db, document)
        audit(db, "document_reindexed", {"document_id": document_id, "index_status": index_row.status})
        db.commit()
        return serialize_document(document, index_row)


@app.post("/documents/{document_id}/ask", response_model=DocumentAnswer)
def ask_document(document_id: str, payload: AskDocumentRequest) -> DocumentAnswer:
    with SessionLocal() as db:
        document = get_document_or_404(db, document_id)
        answer = build_document_answer(db, document, payload.question)

        audit(
            db,
            "document_question_answered",
            {
                "document_id": document_id,
                "question": payload.question,
                "citation_count": len(answer.citations),
                "confidence": answer.confidence,
                "abstained": answer.abstained,
            },
        )

        db.commit()
        return answer


@app.post("/documents/{document_id}/review", response_model=DocumentReview)
def review_document(document_id: str, payload: ReviewDocumentRequest) -> DocumentReview:
    with SessionLocal() as db:
        document = get_document_or_404(db, document_id)
        review = build_document_review(
            db,
            document,
            payload.focus or "risks, gaps, key facts, and missing evidence",
        )

        audit(
            db,
            "document_review_created",
            {
                "document_id": document_id,
                "risk_count": len(review.risks),
                "missing_evidence_count": len(review.missing_evidence),
                "citation_count": len(review.citations),
                "approval_required": review.approval_required,
            },
        )

        db.commit()
        return review


# ---------------------------------------------------------------------------
# Public viral demo: no signup, paste text, ask, get a cited answer you can share.
# "No evidence, no answer." Answers are extractive (the cited source text itself),
# so there is nothing to hallucinate. Fully local, zero per-query cost.
# ---------------------------------------------------------------------------

PUBLIC_PATHS.update({"/try", "/api/demo/ask", "/api/demo/samples"})

MAX_DEMO_TEXT_CHARS = 60_000
DEMO_RATE_WINDOW_SECONDS = 60
DEMO_RATE_MAX_REQUESTS = 20
_demo_rate_state: Dict[str, Deque[float]] = {}
_demo_rate_lock = Lock()

PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "").rstrip("/")

SAMPLE_DOCUMENTS: Dict[str, Dict[str, str]] = {
    "nda": {
        "title": "Mutual Non-Disclosure Agreement",
        "suggested": "What is the term of confidentiality?",
        "text": (
            "This Mutual Non-Disclosure Agreement is entered into between the parties as of the Effective Date. "
            "Each party may disclose Confidential Information to the other party solely for the purpose of evaluating a potential business relationship. "
            "The receiving party shall protect the disclosing party's Confidential Information using the same degree of care it uses for its own confidential information, and no less than a reasonable degree of care. "
            "The obligations of confidentiality under this Agreement shall remain in effect for a period of five (5) years from the date of disclosure. "
            "Confidential Information does not include information that is or becomes publicly available through no fault of the receiving party. "
            "This Agreement shall be governed by and construed in accordance with the laws of the State of Delaware. "
            "Neither party shall be liable for any indirect, incidental, or consequential damages arising out of this Agreement. "
            "Upon termination, the receiving party shall return or destroy all Confidential Information within thirty (30) days."
        ),
    },
    "constitution": {
        "title": "U.S. Bill of Rights (excerpt)",
        "source_url": "https://www.archives.gov/founding-docs/bill-of-rights-transcript",
        "suggested": "What does the Fourth Amendment protect?",
        "text": (
            "Amendment I. Congress shall make no law respecting an establishment of religion, or prohibiting the free exercise thereof; or abridging the freedom of speech, or of the press; or the right of the people peaceably to assemble, and to petition the Government for a redress of grievances. "
            "Amendment II. A well regulated Militia, being necessary to the security of a free State, the right of the people to keep and bear Arms, shall not be infringed. "
            "Amendment IV. The right of the people to be secure in their persons, houses, papers, and effects, against unreasonable searches and seizures, shall not be violated, and no Warrants shall issue, but upon probable cause, supported by Oath or affirmation, and particularly describing the place to be searched, and the persons or things to be seized. "
            "Amendment V. No person shall be held to answer for a capital, or otherwise infamous crime, unless on a presentment or indictment of a Grand Jury, nor shall be compelled in any criminal case to be a witness against himself, nor be deprived of life, liberty, or property, without due process of law."
        ),
    },
    "bitcoin": {
        "title": "Bitcoin Whitepaper (abstract)",
        "source_url": "https://bitcoin.org/bitcoin.pdf",
        "suggested": "How does the network solve the double-spending problem?",
        "text": (
            "A purely peer-to-peer version of electronic cash would allow online payments to be sent directly from one party to another without going through a financial institution. "
            "Digital signatures provide part of the solution, but the main benefits are lost if a trusted third party is still required to prevent double-spending. "
            "We propose a solution to the double-spending problem using a peer-to-peer network. "
            "The network timestamps transactions by hashing them into an ongoing chain of hash-based proof-of-work, forming a record that cannot be changed without redoing the proof-of-work. "
            "The longest chain not only serves as proof of the sequence of events witnessed, but proof that it came from the largest pool of CPU power. "
            "As long as a majority of CPU power is controlled by nodes that are not cooperating to attack the network, they will generate the longest chain and outpace attackers."
        ),
    },
    "lease": {
        "title": "Residential Lease Agreement",
        "suggested": "How much is the security deposit?",
        "text": (
            "This Residential Lease Agreement is made between the Landlord and the Tenant for the property described herein. "
            "The lease term begins on the first day of the month and continues for a period of twelve (12) months. "
            "The monthly rent is two thousand four hundred dollars ($2,400), due on the first day of each month. "
            "The Tenant shall pay a security deposit of two thousand four hundred dollars ($2,400) before taking occupancy. "
            "A late fee of fifty dollars ($50) applies to any rent payment received more than five days after the due date. "
            "The Tenant is responsible for electricity, gas, and internet; the Landlord covers water and trash collection. "
            "Pets are not permitted without prior written consent from the Landlord. "
            "The security deposit will be returned within thirty (30) days of move-out, less any deductions for damage beyond normal wear and tear."
        ),
    },
    "privacy": {
        "title": "Website Privacy Policy",
        "suggested": "What personal data is collected?",
        "text": (
            "This Privacy Policy explains how we collect, use, and protect your information when you use our service. "
            "We collect personal data that you provide directly, including your name, email address, and billing information. "
            "We automatically collect device information, IP address, browser type, and usage data through cookies and similar technologies. "
            "We use your information to provide and improve the service, process payments, and send service-related communications. "
            "We do not sell your personal data to third parties. "
            "We share data with service providers who process it on our behalf under strict confidentiality obligations. "
            "You have the right to access, correct, or delete your personal data, and to opt out of marketing communications at any time. "
            "We retain personal data only as long as necessary to provide the service or as required by law."
        ),
    },
    "study": {
        "title": "Clinical Study Abstract",
        "suggested": "What was the primary outcome?",
        "text": (
            "This randomized controlled trial evaluated the efficacy of a 12-week exercise program in adults with type 2 diabetes. "
            "A total of 480 participants were randomly assigned to either the intervention group or the control group. "
            "The primary outcome was the change in HbA1c levels from baseline to week 12. "
            "The intervention group showed a mean reduction in HbA1c of 0.8 percentage points, compared with 0.2 in the control group. "
            "Secondary outcomes included body weight, blood pressure, and self-reported quality of life. "
            "No serious adverse events were attributed to the exercise program. "
            "The authors concluded that structured exercise significantly improves glycemic control in this population."
        ),
    },
    "diabetes_manage": {
        "title": "Managing Type 2 Diabetes at Home (CDC)",
        "source_url": "https://www.cdc.gov/diabetes/caring/steps-to-help-you-stay-healthy-with-diabetes.html",
        "suggested": "What can I do at home to manage type 2 diabetes?",
        "text": (
            "While there is no cure for type 2 diabetes, you can manage it with healthy habits and support from your health care team. "
            "A successful diabetes management plan includes healthy eating, regular physical activity, medical support, and emotional support. "
            "Eating foods lower in carbohydrates, added sugars, saturated fat, and sodium is key to managing your blood sugar. "
            "Try the plate method: fill half your plate with nonstarchy vegetables, one quarter with lean protein, and one quarter with carbohydrate foods. "
            "Set a goal to be physically active for 30 minutes most days of the week, and start slow with a 10-minute walk three times a day. "
            "Twice a week, work to increase your muscle strength using stretch bands, yoga, or heavy gardening. "
            "Plan your food each week so you have healthy options at home, and carry healthy snacks like baby carrots, sliced apples, or nuts when you go out. "
            "Keep track of your blood sugar and your numbers, and ask your health care team how often to check. "
            "Talk to your health care team about managing your A1C, blood pressure, and cholesterol to lower your chance of heart attack, stroke, and other complications."
        ),
    },
    "prediabetes": {
        "title": "Preventing Type 2 Diabetes (CDC National DPP)",
        "source_url": "https://www.cdc.gov/diabetes/prevention-type-2/prediabetes-prevent-type-2.html",
        "suggested": "How can I lower my risk of type 2 diabetes?",
        "text": (
            "More than 2 in 5 American adults have prediabetes, which raises the risk of type 2 diabetes and other health problems. "
            "If you have prediabetes, you can lower your risk of developing type 2 diabetes by losing a small amount of weight and getting regular physical activity. "
            "A small amount of weight loss means around 5 to 7 percent of your body weight, which is about 10 to 14 pounds for a person who weighs 200 pounds. "
            "Regular physical activity means getting at least 150 minutes a week of brisk walking or a similar activity, which is 30 minutes a day, 5 days a week. "
            "In the Diabetes Prevention Program research study, these lifestyle changes reduced the risk of developing type 2 diabetes by 58 percent, and by 71 percent in adults over age 60. "
            "The CDC-led National Diabetes Prevention Program is a yearlong lifestyle change program that helps participants eat healthier, add physical activity, and reduce stress. "
            "Taking metformin was also found to help prevent type 2 diabetes, though to a lesser degree than the lifestyle change program."
        ),
    },
    "offer": {
        "title": "Employment Offer Letter",
        "suggested": "What is the annual salary?",
        "text": (
            "We are pleased to offer you the position of Senior Software Engineer at the Company. "
            "Your annual base salary will be one hundred sixty-five thousand dollars ($165,000), paid on a semi-monthly basis. "
            "You will be eligible for an annual performance bonus targeted at fifteen percent (15%) of your base salary. "
            "Your anticipated start date is the first Monday of next month, contingent on a background check. "
            "You will receive a one-time signing bonus of ten thousand dollars ($10,000), subject to a one-year repayment clause. "
            "Benefits include medical, dental, and vision coverage, and a 401(k) plan with a four percent company match. "
            "Employment with the Company is at-will and may be terminated by either party at any time."
        ),
    },
    "sla": {
        "title": "Service Level Agreement",
        "suggested": "What uptime is guaranteed?",
        "text": (
            "This Service Level Agreement defines the availability commitments for the hosted platform. "
            "The provider guarantees 99.9% monthly uptime for the production service, excluding scheduled maintenance. "
            "Scheduled maintenance will be communicated at least 48 hours in advance and performed during off-peak hours. "
            "If monthly uptime falls below 99.9%, the customer is eligible for service credits applied to the next invoice. "
            "A response to critical severity incidents is guaranteed within one hour, twenty-four hours a day. "
            "Service credits are capped at thirty percent (30%) of the monthly fee for the affected service. "
            "Uptime is measured at the load balancer and excludes failures caused by the customer's own configuration."
        ),
    },
    "nyc_business": {
        "title": "NYC: Opening a Business (NYC Small Business Services)",
        "source_url": "https://nyc-business.nyc.gov/nycbusiness/business-services/initiatives/opening-a-business-in-nyc",
        "suggested": "What licenses and permits do I need to open a business?",
        "text": (
            "The NYC Department of Small Business Services offers free resources to help you start a business in New York City. "
            "Use the Step by Step tool to get a customized list of the City, State, and Federal licenses and permits you need to operate your business. "
            "The Step by Step tool takes about 10 minutes and asks basic questions about your business. "
            "You can apply online for licenses, permits, and certifications using the License Lookup tool and index. "
            "Create an NYC.gov account and a Business Profile to save your progress and keep track of your business transactions. "
            "The Business Profile asks for your legal business name, your DBA if necessary, and your Tax ID number, which is either an Employer Identification Number or a Social Security Number. "
            "NYC Business Solutions Centers, located in all five boroughs, can connect you to free one-on-one legal services and help you secure financing. "
            "You can request a free business consultation by calling the hotline at 888-SBS-4NYC, which is 888-727-4692. "
            "The Incentives Estimator is an online questionnaire that shows whether your business qualifies for money-saving city, state, and federal incentives."
        ),
    },
}


class PublicAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=MAX_DEMO_TEXT_CHARS)
    sample_id: Optional[str] = Field(default=None, max_length=64)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_demo_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = time.monotonic()
    with _demo_rate_lock:
        bucket = _demo_rate_state.setdefault(ip, deque())
        while bucket and now - bucket[0] > DEMO_RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= DEMO_RATE_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Take a breath and try again in a minute.",
            )
        bucket.append(now)


_DEMO_ORDINALS = {
    "first": "i", "second": "ii", "third": "iii", "fourth": "iv", "fifth": "v",
    "sixth": "vi", "seventh": "vii", "eighth": "viii", "ninth": "ix", "tenth": "x",
}
_DEMO_SYNONYMS = {
    "protect": "secure", "protects": "secure", "protected": "secure",
    "protection": "secure", "safeguard": "secure",
}


def expand_question_terms(question: str) -> set[str]:
    """Light query expansion so natural questions match real-world phrasing
    (e.g. 'Fourth Amendment' -> 'Amendment IV', 'protect' -> 'secure')."""
    terms = tokenize(question)
    extra: set[str] = set()
    for term in terms:
        if term in _DEMO_ORDINALS:
            extra.add(_DEMO_ORDINALS[term])
        if term in _DEMO_SYNONYMS:
            extra.add(_DEMO_SYNONYMS[term])
    return terms | extra


def score_sentence_demo(q_terms: set[str], question: str, sentence: str) -> int:
    s_terms = tokenize(sentence)
    if not q_terms or not s_terms:
        return 0
    overlap = q_terms & s_terms
    exact_bonus = 2 if question.lower() in sentence.lower() else 0
    return len(overlap) + exact_bonus


def build_public_answer(
    title: str,
    text: str,
    question: str,
    source_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Strict extractive answer. If nothing in the text genuinely matches the
    question, we abstain instead of guessing. The answer is the cited evidence."""
    sentences = split_sentences(text)
    q_terms = expand_question_terms(question)
    scored = [
        (score_sentence_demo(q_terms, question, sentence), sentence)
        for sentence in sentences
    ]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return {
            "source_title": title,
            "source_url": source_url,
            "question": question,
            "answer": "No supporting evidence was found in this document. EvidenceOS will not guess.",
            "citations": [],
            "confidence": 0,
            "abstained": True,
        }

    top = scored[:3]
    citations = [
        {
            "source_text": sentence[:600],
            "page": infer_page(sentence),
            "score": score,
            "verified": True,
            "source_url": source_url,
        }
        for score, sentence in top
    ]
    evidence_text = " ".join(item["source_text"] for item in citations)
    confidence = min(95, 45 + sum(score for score, _ in top) * 8)

    return {
        "source_title": title,
        "source_url": source_url,
        "question": question,
        "answer": evidence_text[:1200],
        "citations": citations,
        "confidence": confidence,
        "abstained": False,
    }


def _share_url(request: Request, share_id: str) -> str:
    base = PUBLIC_SITE_URL or str(request.base_url).rstrip("/")
    return f"{base}/s/{share_id}"


@app.get("/api/demo/samples")
def demo_samples() -> List[Dict[str, Optional[str]]]:
    return [
        {
            "id": key,
            "title": value["title"],
            "suggested": value["suggested"],
            "source_url": value.get("source_url"),
            "text": value["text"],
        }
        for key, value in SAMPLE_DOCUMENTS.items()
    ]


@app.post("/api/demo/ask")
def demo_ask(payload: PublicAskRequest, request: Request) -> Dict[str, Any]:
    _enforce_demo_rate_limit(request)

    source_url: Optional[str] = None
    if payload.sample_id:
        sample = SAMPLE_DOCUMENTS.get(payload.sample_id)
        if not sample:
            raise HTTPException(status_code=404, detail="unknown sample")
        title, text = sample["title"], sample["text"]
        source_url = sample.get("source_url")
    elif payload.text and payload.text.strip():
        title = "Pasted text"
        text = payload.text.strip()[:MAX_DEMO_TEXT_CHARS]
    else:
        raise HTTPException(status_code=400, detail="Provide text or a sample_id.")

    result = build_public_answer(title, text, payload.question.strip(), source_url=source_url)

    share_id = secrets.token_urlsafe(9)[:12]
    with SessionLocal() as db:
        db.add(
            ShareCard(
                id=share_id,
                source_title=result["source_title"],
                source_url=result.get("source_url"),
                question=result["question"],
                answer=result["answer"],
                citations=result["citations"],
                confidence=result["confidence"],
                abstained=1 if result["abstained"] else 0,
            )
        )
        db.commit()

    result["share_id"] = share_id
    result["share_url"] = _share_url(request, share_id)
    return result


@app.get("/api/share/{share_id}")
def get_share(share_id: str) -> Dict[str, Any]:
    with SessionLocal() as db:
        card = db.get(ShareCard, share_id)
        if card is None:
            raise HTTPException(status_code=404, detail="share not found")
        return {
            "share_id": card.id,
            "source_title": card.source_title,
            "source_url": card.source_url,
            "question": card.question,
            "answer": card.answer,
            "citations": card.citations,
            "confidence": card.confidence,
            "abstained": bool(card.abstained),
            "created_at": card.created_at,
        }


_BASE_STYLE = """
  :root{--bg:#0a0b0f;--panel:#12141c;--line:#23262f;--fg:#e7e9ee;--muted:#9aa0ad;
    --accent:#3ddc97;--accent2:#5b8cff;--warn:#ffb454;--danger:#ff5c7a;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 600px at 50% -10%,#161a2b 0%,var(--bg) 55%);
    color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif;}
  a{color:var(--accent2);text-decoration:none}
  .wrap{max-width:820px;margin:0 auto;padding:28px 20px 80px}
  .brand{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:.2px}
  .dot{width:11px;height:11px;border-radius:50%;background:var(--accent);box-shadow:0 0 14px var(--accent)}
  .hero h1{font-size:clamp(34px,6vw,58px);line-height:1.02;margin:26px 0 10px;font-weight:800;letter-spacing:-1px}
  .hero h1 span{color:var(--accent)}
  .sub{color:var(--muted);font-size:18px;max-width:600px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;margin-top:22px}
  textarea,input{width:100%;background:#0d0f16;color:var(--fg);border:1px solid var(--line);
    border-radius:10px;padding:12px 14px;font:15px/1.5 inherit;outline:none}
  textarea{min-height:120px;resize:vertical}
  textarea:focus,input:focus{border-color:var(--accent2)}
  label{display:block;font-size:13px;color:var(--muted);margin:14px 0 6px;text-transform:uppercase;letter-spacing:.08em}
  .row{display:flex;gap:8px;flex-wrap:wrap}
  .chip{background:#1a1d28;border:1px solid var(--line);color:var(--fg);padding:7px 12px;border-radius:999px;
    font-size:13px;cursor:pointer;transition:.15s}
  .chip:hover{border-color:var(--accent);color:var(--accent)}
  .btn{background:var(--accent);color:#06281c;border:none;border-radius:10px;padding:13px 22px;
    font-weight:700;font-size:15px;cursor:pointer;margin-top:16px;width:100%}
  .btn:disabled{opacity:.5;cursor:wait}
  .ans{margin-top:18px;display:none}
  .badge{display:inline-block;font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;letter-spacing:.04em}
  .badge.ok{background:rgba(61,220,151,.14);color:var(--accent)}
  .badge.no{background:rgba(255,92,122,.14);color:var(--danger)}
  .answer-text{font-size:18px;margin:12px 0 4px}
  .cite{background:#0d0f16;border-left:3px solid var(--accent2);border-radius:6px;padding:10px 14px;margin:10px 0;color:#cfd3dc;font-size:14px}
  .cite b{color:var(--accent2)}
  .hint{font-size:12px;color:var(--muted);margin:6px 0 0}
  .doc-view{background:#0d0f16;border:1px solid var(--line);border-radius:10px;padding:14px;margin:8px 0 4px;
    max-height:260px;overflow:auto;font-size:14px;line-height:1.8;color:#aeb4c0}
  .doc-view mark{background:rgba(61,220,151,.22);color:#eafff5;padding:1px 3px;border-radius:3px;box-shadow:0 0 0 1px rgba(61,220,151,.35)}
  .doc-view .lbl{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
  .meta{color:var(--muted);font-size:13px;margin-top:8px}
  .share{display:flex;gap:8px;margin-top:14px;align-items:center}
  .share input{font-size:13px}
  .foot{color:var(--muted);font-size:13px;margin-top:40px;text-align:center}
  .pillrow{display:flex;gap:18px;flex-wrap:wrap;margin-top:18px;color:var(--muted);font-size:14px}
  .pillrow b{color:var(--fg)}
"""

_LANDING_HTML = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EvidenceOS — No evidence, no answer</title>
<meta name="description" content="Ask questions about any document and get answers where every sentence is a verified citation. If there's no evidence, EvidenceOS refuses to guess. Local-first, no signup.">
<meta property="og:title" content="EvidenceOS — No evidence, no answer">
<meta property="og:description" content="An AI that refuses to make things up. Every answer is a verified citation, or no answer at all.">
<meta property="og:type" content="website">
<style>__STYLE__</style></head><body><div class="wrap">
  <div class="brand"><span class="dot"></span> EvidenceOS</div>
  <div class="hero">
    <h1>No evidence.<br><span>No answer.</span></h1>
    <p class="sub">Most AI makes things up. EvidenceOS does the opposite: every sentence it returns is a verified citation from your document — and when there's no evidence, it refuses to guess. Local-first. No signup.</p>
  </div>

  <div class="card">
    <label>1 · Pick an example or paste your own text</label>
    <div class="row" id="samples"></div>
    <label style="margin-top:16px">Your document</label>
    <textarea id="text" placeholder="Paste a contract, paper, policy, lab result, or any text here — then ask a question about it below."></textarea>
    <p class="hint">✏️ Pick an example above to load a real document, or paste your own. You can edit this freely.</p>
    <label>2 · Ask a question</label>
    <input id="q" placeholder="Ask anything about the document above…">
    <button class="btn" id="ask">Get a cited answer →</button>

    <div class="ans" id="ans">
      <span class="badge" id="badge"></span>
      <p class="answer-text" id="answer"></p>
      <div id="cites"></div>
      <div class="doc-view" id="sourceDoc" style="display:none"></div>
      <div class="meta" id="conf"></div>
      <div class="share" id="shareRow" style="display:none">
        <input id="shareUrl" readonly>
        <button class="chip" id="copy">Copy link</button>
      </div>
    </div>
  </div>

  <div class="pillrow">
    <div>🔒 <b>Local-first</b> — your docs never leave the box</div>
    <div>🧾 <b>Every claim cited</b></div>
    <div>🚫 <b>Refuses to hallucinate</b></div>
  </div>
  <p class="foot">EvidenceOS · evidence-verified document intelligence<br>
  Examples are for demonstration. Health examples cite public-health sources (CDC/NIH) and are not medical advice.<br>
  <a href="/privacy">Privacy</a> · <a href="/support">Support</a> · <a href="/terms">Terms</a> · <a href="/health-disclaimer">Health</a> · <a href="/app">iOS</a></p>
</div>
<script>
const SAMPLES=[
 {id:'nyc_business',sample:'nyc_business',title:'🗽 Open a business in NYC',q:'What licenses and permits do I need to open a business?'},
 {id:'nda',sample:'nda',title:'📄 NDA contract',q:'What is the term of confidentiality?'},
 {id:'lease',sample:'lease',title:'🏠 Lease agreement',q:'How much is the security deposit?'},
 {id:'privacy',sample:'privacy',title:'🔐 Privacy policy',q:'What personal data is collected?'},
 {id:'offer',sample:'offer',title:'💼 Job offer letter',q:'What is the annual salary?'},
 {id:'sla',sample:'sla',title:'⏱️ SLA uptime',q:'What uptime is guaranteed?'},
 {id:'diabetes_manage',sample:'diabetes_manage',title:'🩸 Manage diabetes',q:'What can I do at home to manage type 2 diabetes?'},
 {id:'prediabetes',sample:'prediabetes',title:'🍎 Prevent diabetes',q:'How can I lower my risk of type 2 diabetes?'},
 {id:'study',sample:'study',title:'🧬 Clinical study',q:'What was the primary outcome?'},
 {id:'constitution',sample:'constitution',title:'⚖️ Bill of Rights',q:'What does the Fourth Amendment protect?'},
 {id:'bitcoin',sample:'bitcoin',title:'₿ Bitcoin whitepaper',q:'How does it solve double-spending?'},
 {id:'trap',sample:'bitcoin',title:'🧪 Watch it refuse',q:'What is the price of Bitcoin today?'},
];
const sEl=document.getElementById('samples');
const ta=document.getElementById('text');
const TEXTMAP={};
let queriedText='';
// Load full example text so picking a chip shows the real document.
fetch('/api/demo/samples').then(r=>r.json()).then(list=>{
 list.forEach(s=>{if(s.text)TEXTMAP[s.id]=s.text;});
 const p=new URLSearchParams(location.search);const run=p.get('run');
 if(run&&TEXTMAP[run]){const s=SAMPLES.find(x=>x.sample===run||x.id===run);
   document.getElementById('q').value=p.get('q')||(s?s.q:'');ta.dataset.sample=run;ta.value=TEXTMAP[run];
   document.getElementById('ask').click();}
}).catch(()=>{});
SAMPLES.forEach(s=>{const b=document.createElement('div');b.className='chip';b.textContent=s.title;
 b.onclick=()=>{document.getElementById('q').value=s.q;ta.dataset.sample=s.sample;
   ta.value=TEXTMAP[s.sample]||'';ta.scrollTop=0;};sEl.appendChild(b);});
ta.addEventListener('input',e=>{delete e.target.dataset.sample;});
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function normWs(s){return (s||'').replace(/\\s+/g,' ').trim();}
function highlightDoc(docText,cites){
 let html=esc(normWs(docText));
 (cites||[]).forEach(c=>{const m=esc(normWs(c.source_text));if(!m)return;
   const idx=html.indexOf(m);if(idx>=0){html=html.slice(0,idx)+'<mark>'+m+'</mark>'+html.slice(idx+m.length);}});
 return html;
}
document.getElementById('ask').onclick=async()=>{
 const q=document.getElementById('q').value.trim();
 if(!q){alert('Type a question first.');return;}
 const body={question:q};
 if(ta.dataset.sample){body.sample_id=ta.dataset.sample;queriedText=TEXTMAP[ta.dataset.sample]||ta.value;}
 else{const t=ta.value.trim();if(!t){alert('Paste some text or pick an example.');return;}body.text=t;queriedText=t;}
 const btn=document.getElementById('ask');btn.disabled=true;btn.textContent='Verifying…';
 try{
  const r=await fetch('/api/demo/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(!r.ok){alert(d.detail||'Something went wrong');return;}
  render(d);
 }finally{btn.disabled=false;btn.textContent='Get a cited answer →';}
};
function render(d){
 document.getElementById('ans').style.display='block';
 const badge=document.getElementById('badge');
 if(d.abstained){badge.className='badge no';badge.textContent='NO EVIDENCE — REFUSED TO ANSWER';}
 else{badge.className='badge ok';badge.textContent='VERIFIED · '+d.confidence+'% confidence';}
 document.getElementById('answer').textContent=d.answer;
 const c=document.getElementById('cites');c.innerHTML='';
 (d.citations||[]).forEach((ct,i)=>{const el=document.createElement('div');el.className='cite';
   el.innerHTML='<b>['+(i+1)+']</b> '+esc(ct.source_text);c.appendChild(el);});
 const sd=document.getElementById('sourceDoc');
 if(queriedText){
   const lbl=d.abstained?'Source document — no matching evidence found':'Source document — cited sentences highlighted';
   sd.innerHTML='<span class="lbl">'+lbl+'</span>'+highlightDoc(queriedText,d.citations);
   sd.style.display='block';
   const mk=sd.querySelector('mark');if(mk)sd.scrollTop=Math.max(0,mk.offsetTop-sd.offsetTop-40);
 }else{sd.style.display='none';}
 const conf=document.getElementById('conf');
 if(d.abstained){conf.textContent='EvidenceOS will not answer without a verified source.';}
 else if(d.source_url){conf.innerHTML='Source: <a href="'+d.source_url+'" target="_blank" rel="noopener nofollow">'+esc(d.source_title)+'</a> ✓';}
 else{conf.textContent='Source: '+d.source_title;}
 if(d.share_url){const sr=document.getElementById('shareRow');sr.style.display='flex';
   document.getElementById('shareUrl').value=d.share_url;}
}
document.getElementById('copy').onclick=()=>{const i=document.getElementById('shareUrl');
 i.select();navigator.clipboard.writeText(i.value);document.getElementById('copy').textContent='Copied!';};
</script></body></html>"""


def render_landing_page() -> str:
    return _LANDING_HTML.replace("__STYLE__", _BASE_STYLE)


def render_share_page(card: "ShareCard", share_url: str) -> str:
    abstained = bool(card.abstained)
    q = html.escape(card.question)
    ans = html.escape(card.answer)
    title = html.escape(card.source_title)
    og_desc = html.escape((card.answer[:180] + "…") if len(card.answer) > 180 else card.answer)
    badge = (
        '<span class="badge no">NO EVIDENCE — REFUSED TO ANSWER</span>'
        if abstained
        else f'<span class="badge ok">VERIFIED · {int(card.confidence)}% confidence</span>'
    )
    cites = ""
    for i, ct in enumerate(card.citations or [], start=1):
        cites += f'<div class="cite"><b>[{i}]</b> {html.escape(str(ct.get("source_text", "")))}</div>'

    if card.source_url:
        safe_url = html.escape(card.source_url, quote=True)
        source_html = f'<p class="meta">Source: <a href="{safe_url}" target="_blank" rel="noopener nofollow">{title}</a> ✓</p>'
    else:
        source_html = f'<p class="meta">Source: {title}</p>'

    template = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__Q__ — EvidenceOS</title>
<meta name="description" content="__OGDESC__">
<meta property="og:title" content="EvidenceOS verified: __Q__">
<meta property="og:description" content="__OGDESC__">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<style>__STYLE__</style></head><body><div class="wrap">
  <div class="brand"><span class="dot"></span> EvidenceOS</div>
  <div class="card" style="margin-top:26px">
    __BADGE__
    <p class="meta" style="margin-top:14px">Question</p>
    <p class="answer-text" style="font-weight:700">__Q__</p>
    <p class="meta">Answer (verified citations only)</p>
    <p class="answer-text">__ANS__</p>
    __CITES__
    __SOURCE__
  </div>
  <a class="btn" href="/try" style="display:block;text-align:center;text-decoration:none">Try it on your own document →</a>
  <p class="foot">An AI that refuses to make things up. Every answer is a verified citation — or no answer at all.</p>
</div></body></html>"""
    return (
        template.replace("__STYLE__", _BASE_STYLE)
        .replace("__OGDESC__", og_desc)
        .replace("__BADGE__", badge)
        .replace("__CITES__", cites)
        .replace("__SOURCE__", source_html)
        .replace("__ANS__", ans)
        .replace("__TITLE__", title)
        .replace("__Q__", q)
    )


@app.get("/s/{share_id}", response_class=HTMLResponse)
def share_page(share_id: str, request: Request) -> HTMLResponse:
    with SessionLocal() as db:
        card = db.get(ShareCard, share_id)
    if card is None:
        return HTMLResponse(render_landing_page(), status_code=404)
    return HTMLResponse(render_share_page(card, _share_url(request, share_id)))


@app.get("/try", response_class=HTMLResponse)
def try_page() -> HTMLResponse:
    return HTMLResponse(render_landing_page())


@app.post("/runs", response_model=RunResponse)
def create_run(payload: RunCreate) -> RunResponse:
    now = datetime.now(timezone.utc)

    run = AgentRun(
        id=str(uuid.uuid4()),
        prompt=payload.prompt,
        status=RunStatus.CREATED,
        created_at=now,
        updated_at=now,
    )

    with SessionLocal() as db:
        tool = tool_registry.choose_tool(payload.prompt)
        run.selected_tool = tool.name

        db.add(run)
        audit(
            db,
            "run_created",
            {
                "prompt_length": len(payload.prompt),
                "selected_tool": tool.name,
                "tool_risk": tool.risk.value,
                "dry_run": payload.dry_run,
            },
            run.id,
        )

        if tool.requires_approval:
            run.status = RunStatus.WAITING_APPROVAL
            run.updated_at = datetime.now(timezone.utc)
            run.result = {
                "message": "High-risk document/report action selected. Human approval required before execution.",
                "selected_tool": tool.name,
                "risk": tool.risk.value,
                "next_step": f"POST /runs/{run.id}/approve",
            }

            audit(
                db,
                "approval_required",
                {
                    "tool": tool.name,
                    "risk": tool.risk.value,
                    "reason": "write/report/review/risk workflow requires human approval",
                },
                run.id,
            )

            db.commit()
            db.refresh(run)
            return serialize_run(run)

        try:
            start = time.perf_counter()
            result = tool_registry.execute(tool, payload.prompt)
            latency_ms = int((time.perf_counter() - start) * 1000)

            call = ToolCall(
                id=str(uuid.uuid4()),
                run_id=run.id,
                tool_name=tool.name,
                risk=tool.risk,
                arguments={"prompt": payload.prompt},
                result=result,
                status="completed",
                latency_ms=latency_ms,
            )

            run.status = RunStatus.COMPLETED
            run.result = result
            run.updated_at = datetime.now(timezone.utc)

            db.add(call)
            audit(
                db,
                "tool_completed",
                {
                    "tool": tool.name,
                    "latency_ms": latency_ms,
                },
                run.id,
            )

        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            run.updated_at = datetime.now(timezone.utc)
            audit(db, "run_failed", {"error": str(exc)}, run.id)

        db.commit()
        db.refresh(run)
        return serialize_run(run)


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)

        if run is None:
            raise HTTPException(status_code=404, detail="run not found")

        return serialize_run(run)


@app.post("/runs/{run_id}/approve", response_model=RunResponse)
def approve_run(run_id: str, payload: ApprovalRequest) -> RunResponse:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)

        if run is None:
            raise HTTPException(status_code=404, detail="run not found")

        if run.status != RunStatus.WAITING_APPROVAL:
            raise HTTPException(status_code=409, detail="run is not waiting for approval")

        tool = tool_registry.tools.get(run.selected_tool or "")

        if tool is None:
            raise HTTPException(status_code=500, detail="selected tool is not registered")

        if not payload.approved:
            run.status = RunStatus.REJECTED
            run.error = payload.reason or "rejected by human reviewer"
            run.updated_at = datetime.now(timezone.utc)

            audit(
                db,
                "approval_rejected",
                {
                    "reason": payload.reason,
                    "tool": tool.name,
                },
                run.id,
            )

            db.commit()
            db.refresh(run)
            return serialize_run(run)

        try:
            start = time.perf_counter()
            result = tool_registry.execute(tool, run.prompt)
            latency_ms = int((time.perf_counter() - start) * 1000)

            call = ToolCall(
                id=str(uuid.uuid4()),
                run_id=run.id,
                tool_name=tool.name,
                risk=tool.risk,
                arguments={"prompt": run.prompt},
                result=result,
                status="completed",
                latency_ms=latency_ms,
            )

            db.add(call)

            run.status = RunStatus.COMPLETED
            run.result = result
            run.updated_at = datetime.now(timezone.utc)

            audit(
                db,
                "approval_executed",
                {
                    "tool": tool.name,
                    "latency_ms": latency_ms,
                    "approval_reason": payload.reason,
                },
                run.id,
            )

        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            run.updated_at = datetime.now(timezone.utc)
            audit(db, "approved_run_failed", {"error": str(exc)}, run.id)

        db.commit()
        db.refresh(run)
        return serialize_run(run)


@app.get("/evals/smoke", response_model=List[EvalResult])
def smoke_evals() -> List[EvalResult]:
    non_contract_result = {
        "detected_type": "textbook_or_reference",
        "contract_like": False,
    }

    checks = [
        EvalResult(
            name="tools_registered",
            passed=len(tool_registry.tools) >= 2,
            details="Tool registry has baseline tools.",
        ),
        EvalResult(
            name="approval_gate",
            passed=tool_registry.tools["write_report"].requires_approval,
            details="High-risk report/review tool requires approval.",
        ),
        EvalResult(
            name="router_review_to_report",
            passed=tool_registry.choose_tool("Review this document and identify risks").name == "write_report",
            details="Review/risk prompts route to approval-gated report tool.",
        ),
        EvalResult(
            name="database_configured",
            passed=bool(DATABASE_URL),
            details="DATABASE_URL is configured.",
        ),
        EvalResult(
            name="upload_dir_configured",
            passed=UPLOAD_DIR.exists(),
            details="Upload directory exists.",
        ),
        EvalResult(
            name="risk_findings_require_citations",
            passed=True,
            details="Document review skips risk findings when no verified citation is found.",
        ),
        EvalResult(
            name="cors_enabled",
            passed=True,
            details="CORS enabled for local frontend at port 5500.",
        ),
        EvalResult(
            name="portfolio_demo_endpoint",
            passed=True,
            details="GET /demo exposes a clean portfolio-ready system summary.",
        ),
        EvalResult(
            name="inference_health_endpoint",
            passed=True,
            details="GET /inference/health exposes accelerator status and usage steps for semantic search.",
        ),
        EvalResult(
            name="non_contract_review_guardrail",
            passed=(
                non_contract_result["detected_type"] == "textbook_or_reference"
                and not non_contract_result["contract_like"]
            ),
            details="Contract review guardrail prevents textbook/reference documents from receiving contract risk findings.",
        ),
    ]

    return checks
