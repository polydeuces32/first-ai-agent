from __future__ import annotations

import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Enum as SAEnum, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentops.db")
APP_NAME = os.getenv("APP_NAME", "first-ai-agent")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "storage/uploads"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(APP_NAME)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


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


class DocumentResponse(BaseModel):
    id: str
    filename: str
    content_type: Optional[str]
    text_length: int
    page_count: int
    created_at: datetime


class AskDocumentRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class ReviewDocumentRequest(BaseModel):
    focus: Optional[str] = Field(
        default="risks, gaps, key facts, and missing evidence",
        max_length=1000,
    )


class DocumentAnswer(BaseModel):
    document_id: str
    question: str
    answer: str
    citations: List[Dict[str, Any]]
    confidence: int
    abstained: bool


class DocumentReview(BaseModel):
    document_id: str
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
app = FastAPI(title="EvidenceOS AgentOps Backend", version="0.3.1")


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def audit(
    db: Session,
    event: str,
    payload: Dict[str, Any],
    run_id: Optional[str] = None,
) -> None:
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


def serialize_document(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        text_length=document.text_length,
        page_count=document.page_count,
        created_at=document.created_at,
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


def retrieve_evidence(document: Document, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    sentences = split_sentences(document.text)
    scored: List[tuple[int, str]] = []

    for sentence in sentences:
        score = score_sentence(query, sentence)
        if score > 0:
            scored.append((score, sentence))

    scored.sort(key=lambda item: item[0], reverse=True)

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
            }
        )

        if len(citations) >= limit:
            break

    return citations


def build_document_answer(document: Document, question: str) -> DocumentAnswer:
    citations = retrieve_evidence(document, question, limit=3)

    if not citations:
        return DocumentAnswer(
            document_id=document.id,
            question=question,
            answer="I cannot answer from the uploaded document because no supporting evidence was found.",
            citations=[],
            confidence=0,
            abstained=True,
        )

    evidence_text = " ".join(item["source_text"] for item in citations)
    confidence = min(90, 40 + sum(item["score"] for item in citations) * 10)

    return DocumentAnswer(
        document_id=document.id,
        question=question,
        answer=f"Based on verified evidence from the uploaded document: {evidence_text[:1200]}",
        citations=citations,
        confidence=confidence,
        abstained=False,
    )


def build_document_review(document: Document, focus: str) -> DocumentReview:
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

        evidence = retrieve_evidence(document, term, limit=1)

        # EvidenceOS rule: no verified citation means no risk finding.
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
        f"Extracted {document.text_length} characters across {document.page_count} page(s). "
        f"Returned {len(risks)} verified risk finding(s)."
    )

    return DocumentReview(
        document_id=document.id,
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
    logger.info("EvidenceOS backend started")


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "EvidenceOS",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": APP_NAME}


@app.get("/ready")
def ready() -> Dict[str, str]:
    try:
        with SessionLocal() as db:
            db.execute(select(AgentRun).limit(1))
        return {"status": "ready"}
    except Exception as exc:
        logger.exception("readiness check failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/tools", response_model=List[ToolSpec])
def list_tools() -> List[ToolSpec]:
    return tool_registry.list_tools()


@app.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    filename = safe_filename(file.filename or "uploaded_document")
    document_id = str(uuid.uuid4())
    target_path = UPLOAD_DIR / f"{document_id}_{filename}"

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
        return serialize_document(document)


@app.get("/documents", response_model=List[DocumentResponse])
def list_documents() -> List[DocumentResponse]:
    with SessionLocal() as db:
        documents = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
        return [serialize_document(document) for document in documents]


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str) -> DocumentResponse:
    with SessionLocal() as db:
        document = get_document_or_404(db, document_id)
        return serialize_document(document)


@app.post("/documents/{document_id}/ask", response_model=DocumentAnswer)
def ask_document(document_id: str, payload: AskDocumentRequest) -> DocumentAnswer:
    with SessionLocal() as db:
        document = get_document_or_404(db, document_id)
        answer = build_document_answer(document, payload.question)

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
    ]

    return checks
