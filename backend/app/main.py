from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Enum as SAEnum, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentops.db")
APP_NAME = os.getenv("APP_NAME", "first-ai-agent")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

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
                "answer": "Agent run completed locally. Connect document upload, retrieval, and citation verification next.",
                "input_summary": prompt[:500],
            }

        if tool.name == "write_report":
            return {
                "report": {
                    "title": "EvidenceOS Document Review Report",
                    "summary": prompt[:1000],
                    "risk_findings": [
                        {
                            "risk": "Document evidence layer is not connected yet.",
                            "severity": "medium",
                            "reason": "The backend can run approval-gated reports, but uploaded document retrieval is the next required layer.",
                            "citation": None,
                        }
                    ],
                    "missing_evidence": [
                        "No uploaded document has been attached to this run yet.",
                        "No citation verifier has been connected yet.",
                    ],
                    "approval_status": "approved",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            }

        raise ValueError(f"Unknown tool: {tool.name}")


tool_registry = ToolRegistry()
app = FastAPI(title="EvidenceOS AgentOps Backend", version="0.2.0")


def init_db() -> None:
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
    ]
    return checks
