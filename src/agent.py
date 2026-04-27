#!/usr/bin/env python3
"""
first-ai-agent: a local-first terminal agent for Ollama (macOS-friendly)

What this version fixes/improves:
- Python 3.8+ compatible typing (no `list[dict]` syntax)
- Defensive JSON parsing (handles imperfect model outputs)
- Safer command execution: allowlist + blocks pipes/chaining/redirection
- Clear agent direction: general questions answered directly (no tools)
- "WOW REPORT" mode: type `wow report` to generate reports/WOW_REPORT.md
"""

import os
import json
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None  # type: ignore
from rich.console import Console
from rich.panel import Panel


# ----------------------------
# Settings
# ----------------------------
# LLM backend: "ollama" | "openai" | "none" (no model, no internet, no GPU/CPU for inference)
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").strip().lower()
if LLM_BACKEND not in ("ollama", "openai", "none"):
    LLM_BACKEND = "ollama"

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", os.getenv("OPENAI_MODEL", "bitcoin-brain:latest"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# OpenAI-compatible (used when LLM_BACKEND=openai): LM Studio, Groq, OpenAI, Together, etc.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"  # Put PDFs and .txt/.md here for the agent to read
REPORTS_DIR = BASE_DIR / "reports"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
DOCUMENTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

console = Console()

# Keep small; expand as you grow.
ALLOWED_CMDS = {
    "ls", "pwd", "cat", "head", "tail", "du", "df", "find", "grep",
    "wc", "whoami", "date", "echo", "python3", "pip", "brew", "ollama"
}

# Block obvious shell metacharacters / chaining
BLOCKED_TOKENS = {";", "&&", "||", "|", ">", ">>", "<", "`", "$(", "${"}

# Allowed commands for WOW REPORT (single commands only; no pipes/chaining)
WOW_COMMANDS = [
    "pwd",
    "whoami",
    "df -h /",
    "ollama list",
    "brew --prefix",
    'du -sh "$(brew --cache)"',
    'du -sh "$(brew --prefix)"',
    "du -sh ~/.ollama/models",
    "du -sh ~/Downloads",
]


SYSTEM_PROMPT = """You are a local-first AI agent running on a Mac terminal. Everything runs offline.

You have tools:
- read_file(path)          # Any text file in the project
- write_file(path, content)
- run_cmd(command)         # allowlisted commands only, no pipes/chaining/redirection
- read_document(path)      # PDF, .txt, .md in data/documents/ (e.g. path="handbook.pdf" or "report.pdf")
- list_documents()         # List available docs in data/documents/ (no args)

DOCUMENTS (offline, your own content):
- The user can put PDFs and .txt/.md files in data/documents/. They can add more over time.
- Use list_documents to see what's there. Use read_document(path="filename.pdf") to read one.
- Answer questions from that content (handbooks, reports, notes). All processing is local.

CORE BEHAVIOR:
- If the user asks a general question (learning, ideas, explanations), DO NOT use tools. Answer directly.
- Only use tools when the user explicitly asks you to: run a command, inspect files, read/write a file, read a document/PDF, or generate a report.
- When you do use tools, prefer the smallest number of commands needed.

WOW MODE:
If the user message is exactly: "wow report"
Then you MUST:
1) run the WOW commands (one at a time) using run_cmd
2) write a polished report to: reports/WOW_REPORT.md
3) tell the user where it was written and how to open it

OUTPUT FORMAT RULE:
When you need a tool, respond ONLY with a single JSON object (no markdown, no extra text):
{
  "tool": "read_file|write_file|run_cmd|read_document|list_documents|none",
  "args": { ... },
  "final": ""
}
For list_documents use "args": {}. For read_document use "args": {"path": "filename.pdf"}.
If no tool is needed:
{ "tool":"none", "args":{}, "final":"..." }

Be concise, accurate, and helpful. If a command is blocked or not allowlisted, explain a safe alternative.
"""


# ----------------------------
# Tools
# ----------------------------
def resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return p


def read_file(path: str) -> str:
    p = resolve_path(path)
    if not p.exists():
        return f"[read_file] Not found: {p}"
    if p.is_dir():
        return f"[read_file] Is a directory: {p}"
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"[read_file] Failed to read {p}: {e}"


def write_file(path: str, content: str) -> str:
    p = resolve_path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[write_file] Wrote {len(content)} chars to {p}"
    except Exception as e:
        return f"[write_file] Failed to write {p}: {e}"


def _extract_pdf_text(p: Path) -> str:
    """Extract text from a PDF file. Works offline (uses pypdf)."""
    if PdfReader is None:
        return "[read_document] PDF support not installed. Run: pip install pypdf"
    try:
        reader = PdfReader(str(p))
        parts: List[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n\n".join(parts) if parts else "[read_document] No text could be extracted from this PDF (may be scanned images)."
    except Exception as e:
        return f"[read_document] Failed to read PDF {p}: {e}"


def read_document(path: str) -> str:
    """
    Read a document from the project. Use for PDFs and text files in data/documents.
    Path can be a filename (e.g. handbook.pdf) under data/documents, or a path like data/documents/report.pdf.
    Supports .pdf, .txt, .md. Fully offline.
    """
    p = resolve_path(path)
    # If path is just a filename, look in DOCUMENTS_DIR
    if not p.exists() and not path.startswith("/") and "/" not in path.strip():
        p = (DOCUMENTS_DIR / path.strip()).resolve()
    if not p.exists():
        return f"[read_document] Not found: {p}\nTip: Put PDFs in data/documents/ and use the filename, e.g. read_document(path='handbook.pdf')"
    if p.is_dir():
        return f"[read_document] Is a directory: {p}. Use list_documents to see files."
    suf = p.suffix.lower()
    if suf == ".pdf":
        return _extract_pdf_text(p)
    if suf in (".txt", ".md", ".markdown"):
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return f"[read_document] Failed to read {p}: {e}"
    return f"[read_document] Unsupported format: {suf}. Use .pdf, .txt, or .md"


def list_documents() -> str:
    """List PDF and text documents in data/documents so the user can add more and the agent can reference them. Fully offline."""
    if not DOCUMENTS_DIR.exists():
        return "[list_documents] data/documents/ not found."
    names: List[str] = []
    for f in sorted(DOCUMENTS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (".pdf", ".txt", ".md", ".markdown"):
            names.append(f.name)
    if not names:
        return "[list_documents] No documents yet in data/documents/. Add PDF or .txt/.md files there; the agent can then read them with read_document(path='filename.pdf')."
    return "Documents in data/documents:\n" + "\n".join(f"  - {n}" for n in names)


def has_blocked_tokens(command: str) -> Optional[str]:
    for tok in BLOCKED_TOKENS:
        if tok in command:
            return tok
    return None


def run_cmd(command: str) -> str:
    """
    Run a single allowlisted command safely.
    Blocks pipes, chaining, redirection, command substitution, and shells.
    """
    command = (command or "").strip()
    if not command:
        return "[run_cmd] Empty command."

    blocked = has_blocked_tokens(command)
    if blocked:
        return f"[run_cmd] Blocked token detected: {blocked}\nUse a single simple command without pipes/chaining/redirection."

    try:
        parts = shlex.split(command)
    except Exception as e:
        return f"[run_cmd] Could not parse command: {e}"

    if not parts:
        return "[run_cmd] Empty command after parsing."

    cmd = parts[0]

    if cmd in {"bash", "zsh", "sh", "fish"}:
        return f"[run_cmd] Blocked shell: {cmd}"

    if cmd not in ALLOWED_CMDS:
        return f"[run_cmd] Command not allowlisted: {cmd}\nAllowed: {', '.join(sorted(ALLOWED_CMDS))}"

    try:
        out = subprocess.check_output(parts, stderr=subprocess.STDOUT, text=True, timeout=30)
        return out.strip()
    except subprocess.TimeoutExpired:
        return "[run_cmd] Command timed out after 30 seconds."
    except subprocess.CalledProcessError as e:
        msg = (e.output or "").strip()
        return msg if msg else f"[run_cmd] Failed with code {e.returncode}"
    except Exception as e:
        return f"[run_cmd] Failed to run command: {e}"


# ----------------------------
# LLM: Ollama or OpenAI-compatible API
# ----------------------------
def ollama_chat(model: str, messages: List[Dict[str, str]]) -> str:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data.get("message", {}).get("content", "")


def openai_compatible_chat(model: str, messages: List[Dict[str, str]]) -> str:
    """OpenAI-compatible API: LM Studio (local), Groq, OpenAI, Together, etc."""
    url = f"{OPENAI_BASE_URL}/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
    }
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
    r = requests.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    data = r.json()
    choice = data.get("choices", [{}])[0]
    return choice.get("message", {}).get("content", "")


def llm_chat(model: str, messages: List[Dict[str, str]]) -> str:
    if LLM_BACKEND == "openai":
        return openai_compatible_chat(model, messages)
    return ollama_chat(model, messages)


# ----------------------------
# Helpers
# ----------------------------
def log_line(text: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d")
        LOG_DIR.mkdir(exist_ok=True)
        with (LOG_DIR / f"agent_{ts}.log").open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass  # Don't crash if logs dir is read-only (e.g. on some hosts)


def extract_first_json_object(s: str) -> Optional[str]:
    if not s:
        return None
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def safe_json_parse(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    if not s:
        return {"tool": "none", "args": {}, "final": ""}

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    maybe = extract_first_json_object(s)
    if maybe:
        try:
            obj2 = json.loads(maybe)
            if isinstance(obj2, dict):
                return obj2
        except Exception:
            pass

    return {"tool": "none", "args": {}, "final": s}


def normalize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    tool = str(plan.get("tool", "none")).strip().lower()
    args = plan.get("args", {})
    final = plan.get("final", "")

    if tool not in {"read_file", "write_file", "run_cmd", "read_document", "list_documents", "none"}:
        tool = "none"
    if not isinstance(args, dict):
        args = {}
    if not isinstance(final, str):
        final = str(final)

    return {"tool": tool, "args": args, "final": final}


def is_wow_report_request(user_text: str) -> bool:
    return (user_text or "").strip().lower() == "wow report"


def _run_wow_cmd_safe(cmd: str) -> str:
    """Run a hardcoded WOW command with shell=True for $(…) expansion.
    Only called for commands defined in WOW_COMMANDS — never for user input."""
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, timeout=30)
        return out.strip()
    except subprocess.CalledProcessError as e:
        msg = (e.output or "").strip()
        return msg if msg else f"[error code {e.returncode}]"
    except Exception as e:
        return f"[error: {e}]"


def run_wow_commands_collect() -> Dict[str, str]:
    """Run WOW_COMMANDS one by one and return a dict of command->output."""
    results: Dict[str, str] = {}
    for cmd in WOW_COMMANDS:
        results[cmd] = _run_wow_cmd_safe(cmd)
    return results


def build_wow_report(results: Dict[str, str], model_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append(f"# WOW REPORT")
    lines.append("")
    lines.append(f"- Generated: {now}")
    lines.append(f"- Model: `{model_name}`")
    lines.append(f"- Project: `{BASE_DIR}`")
    lines.append("")
    lines.append("## Snapshot")
    lines.append("")

    def block(title: str, cmd: str):
        out = results.get(cmd, "").strip()
        lines.append(f"### {title}")
        lines.append(f"**Command:** `{cmd}`")
        lines.append("")
        lines.append("```")
        lines.append(out if out else "(no output)")
        lines.append("```")
        lines.append("")

    block("Where the agent is running", "pwd")
    block("Current user", "whoami")
    block("Disk usage (root)", "df -h /")
    block("Ollama models", "ollama list")
    block("Homebrew prefix", "brew --prefix")
    block("Homebrew cache size", 'du -sh "$(brew --cache)"')
    block("Homebrew install size", 'du -sh "$(brew --prefix)"')
    block("Ollama local models size", "du -sh ~/.ollama/models")
    block("Downloads size", "du -sh ~/Downloads")

    lines.append("## Quick wins (safe, no uninstalling)")
    lines.append("")
    lines.append("- Clear Homebrew cache (keeps installs): `brew cleanup -s`")
    lines.append("- Empty Trash (if needed): `rm -rf ~/.Trash/*`")
    lines.append("- Clear a single huge cache folder under `~/Library/Caches/` (targeted, not everything).")
    lines.append("")

    lines.append("## Next upgrades for a stronger agent")
    lines.append("")
    lines.append("1) **Memory**: store preferences + short notes in `data/memory.json`.")
    lines.append("2) **Skills**: add a `skills/` folder (devops cleanup, project bootstrap, code review).")
    lines.append("3) **Better tool routing**: add explicit commands like `scan space`, `summarize repo`, `write readme`.")
    lines.append("")

    lines.append("## Try this next")
    lines.append("")
    lines.append("- In the agent: `Run df -h / and explain it.`")
    lines.append("- Or: `Scan my ~/Library/Caches and tell me the top 5 largest folders.`")
    lines.append("")

    return "\n".join(lines)


# ----------------------------
# No-LLM mode: simple intents, no internet, no model on your hardware
# ----------------------------
def _offline_document_names() -> List[str]:
    """Return list of document filenames (e.g. bitcoin.pdf) in data/documents."""
    if not DOCUMENTS_DIR.exists():
        return []
    return [
        f.name for f in sorted(DOCUMENTS_DIR.iterdir())
        if f.is_file() and f.suffix.lower() in (".pdf", ".txt", ".md", ".markdown")
    ]


def _offline_intent(user: str) -> Optional[str]:
    """Returns intent: 'list_documents', 'read_document', or None."""
    u = (user or "").strip().lower()
    if not u:
        return None
    if u in ("help", "?", "commands", "how can you help", "how can you help me", "what can you do", "how can i use this"):
        return "help"
    if u in ("what documents do we have", "what documents", "list documents", "documents", "show documents"):
        return "list_documents"
    if u.startswith("read "):
        return "read_document"
    return None


def _offline_read_document_path(user: str) -> str:
    """Extract document path from 'read <path>'."""
    u = (user or "").strip()
    if u.lower().startswith("read "):
        return u[5:].strip()
    return ""


# Many ways to ask about a topic (one-shot). Longest prefixes first so "what are the main points of " beats "what are ".
_OFFLINE_QUESTION_PREFIXES = (
    "what are the main points of ", "what are the key points of ", "main points of ", "key points of ",
    "give me a summary of ", "summarize ", "summary of ",
    "can you explain ", "could you explain ", "can you describe ",
    "i want to know about ", "i'd like to know about ", "i need to know about ",
    "what do you know about ", "what does the doc say about ",
    "information about ", "info on ", "info about ",
    "basics of ", "basics about ", "introduction to ", "intro to ",
    "tell me about ", "tell me more about ",
    "what is ", "what's ", "what are ", "what was ", "what were ",
    "explain ", "describe ",
    "how does ", "how do ", "why is ", "why are ", "when was ", "when is ",
    "who created ", "who made ", "who wrote ", "who invented ",
    "highlights of ",
)


def _offline_topic_from_question(user: str) -> Optional[str]:
    """Extract topic from many question forms. Returns the subject (e.g. 'bitcoin') or None."""
    u = (user or "").strip().lower().rstrip("?.!")
    for prefix in _OFFLINE_QUESTION_PREFIXES:
        if u.startswith(prefix):
            topic = u[len(prefix):].strip()
            # Drop trailing "?" and common suffixes
            topic = topic.rstrip("?").strip()
            # "how does X work" -> take first word(s) as topic; "summary of X" -> X
            if not topic:
                continue
            # If topic has many words, keep the part that likely matches a doc (e.g. "bitcoin" not "bitcoin work")
            words = topic.split()
            for n in range(len(words), 0, -1):
                candidate = " ".join(words[:n])
                if _offline_find_document_for_topic(candidate):
                    return candidate
            return topic
    return None


def _offline_find_document_for_topic(topic: str) -> Optional[str]:
    """If a document name matches the topic (e.g. bitcoin -> bitcoin.pdf), return filename.
    Prefer exact stem match so 'what is bitcoin' uses bitcoin.pdf, not Bitcoin_dataset.pdf."""
    topic = (topic or "").strip().lower()
    if not topic:
        return None
    names = _offline_document_names()
    # Exact stem match first (e.g. bitcoin -> bitcoin.pdf)
    for name in names:
        if Path(name).stem.lower() == topic:
            return name
    # Then partial match (e.g. cryptography -> Introduction_to_Modern_Cryptography_2nd.pdf)
    for name in names:
        stem = Path(name).stem.lower()
        if topic in stem or stem in topic:
            return name
    return None


# Max chars to show when answering "what is X" from a doc (no model to summarize)
OFFLINE_DOC_ANSWER_MAX_CHARS = 8000

# QA mode: ask many questions about one subject (no LLM; we search the doc for relevant passages)
_qa_doc_name: Optional[str] = None
_qa_content: Optional[str] = None


def _offline_ask_about_subject(user: str) -> Optional[Tuple[str, str]]:
    """Parse 'ask about X' / 'qa X'. Return (subject, doc_name) or None."""
    u = (user or "").strip().lower()
    for prefix in ("ask about ", "qa ", "questions about ", "ask "):
        if u.startswith(prefix):
            subject = u[len(prefix):].strip().rstrip("?")
            if subject:
                doc_name = _offline_find_document_for_topic(subject)
                if doc_name:
                    return (subject, doc_name)
                return None  # will show "no document for X" below
    return None


def _offline_clear_qa_mode() -> None:
    global _qa_doc_name, _qa_content
    _qa_doc_name = None
    _qa_content = None


# Example question phrasings we show when entering QA mode or when user says "what can I ask"
OFFLINE_QA_EXAMPLE_PHRASINGS = (
    "What is it? / What's the main idea?",
    "How does it work?",
    "Who created it? / Who wrote it?",
    "Why is it important?",
    "When was it introduced?",
    "Give me an example. / Examples?",
    "Summarize the key points.",
    "What problem does it solve?",
    "What are the main components?",
    "Can you explain the basics?",
)


def _offline_qa_find_examples() -> str:
    """Find passages in _qa_content that look like examples (e.g., 'for example', 'e.g.', 'such as')."""
    global _qa_content, _qa_doc_name
    if not _qa_content:
        return "No document loaded. Say 'ask about <subject>' first."
    raw = _qa_content.replace("\r\n", "\n")
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip() and len(p.strip()) > 30]
    example_markers = ("for example", "e.g.", "such as", "for instance", "example:", "examples:", "e.g.,", "e.g ")
    scored: List[tuple] = []
    for p in paragraphs:
        p_lower = p.lower()
        score = sum(1 for m in example_markers if m in p_lower)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    if not scored:
        return "No explicit examples found in the doc. Try asking: 'How does it work?' or 'What are the key points?'"
    out: List[str] = []
    total = 0
    for _, p in scored[:4]:
        if total + len(p) > 3500:
            out.append(p[: 3500 - total] + "...")
            break
        out.append(p)
        total += len(p)
    return "Passages that look like examples:\n\n" + "\n\n---\n\n".join(out)


def _offline_qa_search(question: str) -> str:
    """Search _qa_content for passages relevant to question (keyword match). No LLM."""
    global _qa_content
    if not _qa_content:
        return "No document loaded. Say 'ask about <subject>' first."
    # Split into paragraphs (double newline or long single newline)
    raw = _qa_content.replace("\r\n", "\n")
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip() and len(p.strip()) > 20]
    if not paragraphs:
        paragraphs = [raw[:OFFLINE_DOC_ANSWER_MAX_CHARS]]
    # Keywords: keep content words; include "how", "why", "when", "who" so questions match better
    stop = {"a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "which", "?", ""}
    words = set(w.lower().strip("?!.,") for w in question.split() if w.lower() not in stop and len(w) > 1)
    if not words:
        return paragraphs[0][:2000] + ("..." if len(paragraphs[0]) > 2000 else "")
    # Score each paragraph by number of keyword matches
    scored: List[tuple] = []
    for p in paragraphs:
        p_lower = p.lower()
        score = sum(1 for w in words if w in p_lower)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    if not scored:
        return "No matching passage for that question. Try different words or say 'read " + str(_qa_doc_name or "") + "' for the full doc."
    out: List[str] = []
    total = 0
    max_len = 4000
    for _, p in scored[:5]:
        if total + len(p) > max_len:
            out.append(p[: max_len - total] + "...")
            break
        out.append(p)
        total += len(p)
    return "\n\n".join(out)


def handle_offline_turn(user: str) -> Optional[str]:
    """
    Handle one user turn when LLM_BACKEND=none. Returns response text or None if no intent matched.
    No network, no model - list_documents, read_document, ask about <subject>, and WOW (in main).
    """
    global _qa_doc_name, _qa_content
    u_lower = (user or "").strip().lower()

    # Exit QA mode
    if _qa_content and u_lower in ("done", "back", "exit qa", "stop"):
        _offline_clear_qa_mode()
        return "Left Q&A mode. You can say 'ask about <subject>' again or use other commands."

    # When in QA mode: special intents before generic question search
    if _qa_content and not _offline_intent(user):
        if u_lower in ("examples", "example", "give me an example", "give me examples", "any examples?", "example?"):
            return _offline_qa_find_examples()
        if u_lower in ("what can i ask?", "what can i ask", "example questions", "suggestions", "what should i ask?", "help me ask"):
            lines = ["You can ask in many forms. Examples:\n"] + ["  • " + s for s in OFFLINE_QA_EXAMPLE_PHRASINGS]
            return "\n".join(lines) + "\n\nOr use your own words; I'll find relevant parts of the document."
        return _offline_qa_search(user)

    intent = _offline_intent(user)
    if intent == "help":
        return OFFLINE_HELP
    if intent == "list_documents":
        return list_documents()
    if intent == "read_document":
        path = _offline_read_document_path(user)
        if path:
            return read_document(path)
        return "Usage: read <filename>  e.g. read bitcoin.pdf"

    # "Ask about <subject>" — load doc and enter Q&A mode for all types of questions
    ask_about = _offline_ask_about_subject(user)
    if ask_about is not None:
        subject, doc_name = ask_about
        content = read_document(doc_name)
        if content.startswith("[read_document]"):
            return content
        _qa_doc_name = doc_name
        _qa_content = content
        examples_preview = "\n".join("  • " + s for s in OFFLINE_QA_EXAMPLE_PHRASINGS[:5])
        return (
            f"Ask any question about **{subject}** (from {doc_name}).\n\n"
            "Example phrasings:\n"
            f"{examples_preview}\n\n"
            "You can also say: **examples** (find example passages), **what can I ask?** (more ideas), **done** (leave Q&A)."
        )
    # "ask about X" but no document found
    for prefix in ("ask about ", "qa ", "questions about ", "ask "):
        if u_lower.startswith(prefix):
            subject = u_lower[len(prefix):].strip().rstrip("?")
            if subject:
                return f"No document found for '{subject}'. Use 'list documents' to see available docs."

    # "What is bitcoin" / "explain X" -> read matching document and show content
    topic = _offline_topic_from_question(user)
    if topic:
        doc_name = _offline_find_document_for_topic(topic)
        if doc_name:
            content = read_document(doc_name)
            if content.startswith("[read_document]"):
                return content
            if len(content) > OFFLINE_DOC_ANSWER_MAX_CHARS:
                content = content[:OFFLINE_DOC_ANSWER_MAX_CHARS] + "\n\n[... truncated ...]"
            return f"From **{doc_name}**:\n\n{content}"
    return None


OFFLINE_HELP = (
    "You can ask questions in many forms or use commands. No internet, no model.\n\n"
    "Q&A mode (ask many questions about one subject):\n"
    "  • ask about bitcoin       — then ask anything; say 'examples' or 'what can I ask?' for ideas\n"
    "  • qa <subject>            — same. Say 'done' to leave Q&A.\n\n"
    "One-shot questions (many phrasings work):\n"
    "  • What is bitcoin? / Explain cryptography / Tell me about X\n"
    "  • Can you explain...? / Give me a summary of... / How does X work?\n"
    "  • Who created it? / Why is it important? / What are the key points?\n\n"
    "Commands:\n"
    "  • help                    — show this\n"
    "  • what documents / list documents — list PDFs and docs\n"
    "  • read <name>             — e.g. read bitcoin.pdf\n"
    "  • wow report              — generate reports/WOW_REPORT.md\n"
    "  • done / back             — leave Q&A mode\n"
    "  • exit                    — quit"
)


# ----------------------------
# One turn (for CLI and web): user message in, response text out
# ----------------------------
def process_turn(user: str, messages: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]]]:
    """
    Run one agent turn. Returns (response_text, updated_messages).
    Caller should not pass exit/quit; check before calling.
    """
    model = DEFAULT_MODEL
    endpoint = OLLAMA_URL if LLM_BACKEND == "ollama" else OPENAI_BASE_URL

    if not user.strip():
        return "Type a question or command, or 'help'.", messages

    if is_wow_report_request(user):
        log_line("USER: wow report")
        results = run_wow_commands_collect()
        report = build_wow_report(results, model)
        write_status = write_file("reports/WOW_REPORT.md", report)
        response = (
            "✅ WOW report created.\n\n"
            f"{write_status}\n\n"
            "Open it with: cat reports/WOW_REPORT.md"
        )
        log_line(f"AGENT: {response}")
        return response, messages

    if LLM_BACKEND == "none":
        log_line(f"USER: {user}")
        response = handle_offline_turn(user)
        out = response if response is not None else OFFLINE_HELP
        log_line(f"AGENT: {out}")
        return out, messages

    messages = list(messages)
    messages.append({"role": "user", "content": user})
    log_line(f"USER: {user}")

    try:
        raw = llm_chat(model, messages)
    except Exception as e:
        err = f"Could not reach LLM at {endpoint}\nError: {e}"
        log_line(f"ERROR: {e}")
        return err, messages

    plan = normalize_plan(safe_json_parse(raw))
    tool = plan["tool"]
    args = plan["args"]
    final = (plan["final"] or "").strip()

    if tool == "none":
        log_line(f"AGENT: {final}")
        messages.append({"role": "assistant", "content": final})
        return final or "(no response)", messages

    _TOOL_OUTPUT_LIMIT = 12_000

    tool_output = ""
    if tool == "read_file":
        tool_output = read_file(str(args.get("path", "")))
    elif tool == "write_file":
        tool_output = write_file(str(args.get("path", "")), str(args.get("content", "")))
    elif tool == "run_cmd":
        tool_output = run_cmd(str(args.get("command", "")))
    elif tool == "read_document":
        tool_output = read_document(str(args.get("path", "")))
    elif tool == "list_documents":
        tool_output = list_documents()
    else:
        tool_output = f"[tool] Unknown tool: {tool}"

    if len(tool_output) > _TOOL_OUTPUT_LIMIT:
        tool_output = tool_output[:_TOOL_OUTPUT_LIMIT] + f"\n\n[... truncated: {len(tool_output)} total chars ...]"

    log_line(f"PLAN: {raw}")
    log_line(f"TOOL({tool}): {tool_output}")

    messages.append({"role": "assistant", "content": raw})
    messages.append(
        {
            "role": "user",
            "content": (
                "Tool output:\n"
                f"{tool_output}\n\n"
                "Now respond with tool=none and a clear final answer."
            ),
        }
    )

    try:
        raw2 = llm_chat(model, messages)
    except Exception as e:
        err = f"Tool ran, but LLM call failed.\nError: {e}\n\nTool output:\n{tool_output}"
        log_line(f"ERROR: {e}")
        return err, messages

    plan2 = normalize_plan(safe_json_parse(raw2))
    final2 = (plan2.get("final") or "").strip() or raw2.strip()
    log_line(f"AGENT: {final2}")
    messages.append({"role": "assistant", "content": final2})
    return final2, messages


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    model = DEFAULT_MODEL

    endpoint = ""
    if LLM_BACKEND == "none":
        backend_label = "Offline (no model, no internet)"
    else:
        backend_label = "Ollama" if LLM_BACKEND == "ollama" else "OpenAI-compatible"
        endpoint = OLLAMA_URL if LLM_BACKEND == "ollama" else OPENAI_BASE_URL
    console.print(
        Panel.fit(
            f"[bold]First AI Agent[/bold]\n"
            f"Model: {model}\n"
            f"Backend: {backend_label}"
            + (f" @ {endpoint}" if LLM_BACKEND != "none" else ""),
            title="Ready",
        )
    )
    if LLM_BACKEND == "none":
        console.print("Type [bold]help[/bold] for commands and questions. Type [bold]exit[/bold] to quit.\n")
    else:
        console.print("Type 'exit' to quit.\n")

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user = console.input("[bold cyan]You[/bold cyan]> ").strip()
        if user.lower() in {"exit", "quit"}:
            break
        if is_wow_report_request(user):
            console.print(Panel("Generating WOW report…", title="Agent"))
        response, messages = process_turn(user, messages)
        console.print(Panel(response, title="Agent"))


if __name__ == "__main__":
    main()

