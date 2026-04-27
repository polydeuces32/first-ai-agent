#!/usr/bin/env python3
"""
Minimal web UI for the agent. No IDE or terminal needed after starting.
Run: python run_web.py   (or double-click run_web.command on Mac)
Then open: http://localhost:8765
Uses only stdlib (no Flask). Stays local, no internet (unless you use an API backend).
"""
import base64
import json
import re
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# Run from project root so agent and data paths work
import os
_project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _project_root)
os.chdir(_project_root)
# Default to offline so "what is bitcoin" / "how can you help" use your docs, not a model
if "LLM_BACKEND" not in os.environ:
    os.environ["LLM_BACKEND"] = "none"

from src.agent import process_turn, SYSTEM_PROMPT

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

# Use PORT and 0.0.0.0 when deployed (e.g. Render, Railway); localhost when local
try:
    PORT = int(os.environ.get("PORT") or 8765)
except (TypeError, ValueError):
    PORT = 8765
HOST = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
DOCUMENTS_DIR = os.path.join(_project_root, "data", "documents")
os.makedirs(DOCUMENTS_DIR, exist_ok=True)

# In-memory state (one user)
_chat_messages = [{"role": "system", "content": SYSTEM_PROMPT}]

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>First AI Agent</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 0 auto; padding: 1rem; background: #1a1b26; color: #c0caf5; min-height: 100vh; }
    h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }
    .sub { font-size: 0.85rem; opacity: 0.8; margin-bottom: 1rem; }
    .toolbar { display:flex; flex-wrap:wrap; gap:0.5rem; margin: 1rem 0; }
    .linkbtn { display:inline-flex; align-items:center; justify-content:center; padding:0.6rem 0.8rem; border-radius:6px; background:#292e42; color:#c0caf5; border:1px solid #3b4261; text-decoration:none; font-weight:600; }
    .linkbtn.primary { background:#7aa2f7; color:#1a1b26; border:0; }
    #log { background: #16161e; border: 1px solid #3b4261; border-radius: 8px; padding: 1rem; min-height: 200px; max-height: 50vh; overflow-y: auto; white-space: pre-wrap; word-break: break-word; font-size: 0.9rem; }
    .msg { margin-bottom: 0.75rem; }
    .msg.user { color: #7aa2f7; }
    .msg.agent { color: #9ece6a; }
    form { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
    input[type="text"] { flex: 1; padding: 0.6rem; border: 1px solid #3b4261; border-radius: 6px; background: #16161e; color: #c0caf5; font-size: 1rem; }
    button { padding: 0.6rem 1rem; background: #7aa2f7; color: #1a1b26; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }
    button:hover { background: #89b4fa; }
    .err { color: #f7768e; }
  </style>
</head>
<body>
  <h1>First AI Agent</h1>
  <p class="sub">Local docs &amp; Q&A. Type <strong>help</strong> for commands.</p>
  <div class="toolbar">
    <a class="linkbtn primary" href="/scan">Scan photos to PDF</a>
    <a class="linkbtn" href="/health">Health check</a>
  </div>
  <p class="sub" style="margin-top:0; color:#7aa2f7;">If you see &quot;no server&quot; or can&apos;t connect: start the server first — double-click <strong>run_web.command</strong> or run <strong>.venv/bin/python run_web.py</strong> in the project folder, then open this page.</p>
  <div id="log"></div>
  <form id="f">
    <input type="text" id="input" placeholder="Ask or type help…" autocomplete="off">
    <button type="submit">Send</button>
  </form>
  <script>
    const log = document.getElementById("log");
    const input = document.getElementById("input");
    const f = document.getElementById("f");
    function add(msg, who) {
      const d = document.createElement("div");
      d.className = "msg " + who;
      d.textContent = (who === "user" ? "You: " : "Agent: ") + msg;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }
    async function sendMessage(text) {
      if (!text) return;
      add(text, "user");
      try {
        const r = await fetch("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text }) });
        let j = {};
        try { j = await r.json(); } catch (_) { add("Server error (no JSON). Is the server running?", "agent"); return; }
        if (!r.ok) { add("Error " + r.status + ": " + (j.error || j.response || r.statusText), "agent"); return; }
        add(j.response || j.error || "No response", "agent");
      } catch (err) {
        add("No server. Start it first: double-click run_web.command or run .venv/bin/python run_web.py in the project folder, then open " + location.origin, "agent");
      }
    }
    const params = new URLSearchParams(window.location.search);
    const askDoc = params.get("ask_doc");
    if (askDoc) sendMessage("read " + askDoc);
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      sendMessage(text);
    });
  </script>
</body>
</html>
"""


def safe_filename(name):
    name = (name or "scan.pdf").strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name or "scan.pdf"


def extract_pdf_text_if_any(path):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(path)
        parts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def try_local_ocr(pdf_path):
    """Optional OCR. Uses external tools only when installed. Never blocks normal PDF saving."""
    ocr_txt_path = pdf_path + ".ocr.txt"
    normal_text = extract_pdf_text_if_any(pdf_path)
    if normal_text:
        with open(ocr_txt_path, "w", encoding="utf-8") as f:
            f.write(normal_text)
        return {"ok": True, "mode": "pdf_text", "path": ocr_txt_path, "chars": len(normal_text)}

    try:
        subprocess.check_output(["tesseract", "--version"], stderr=subprocess.STDOUT, text=True, timeout=5)
        subprocess.check_output(["pdftoppm", "-h"], stderr=subprocess.STDOUT, text=True, timeout=5)
    except Exception:
        return {"ok": False, "mode": "missing_tools", "message": "OCR not installed. Run: brew install tesseract poppler && pip install -r requirements-ocr.txt"}

    tmp_prefix = os.path.join(DOCUMENTS_DIR, "_ocr_tmp_page")
    try:
        subprocess.check_output(["pdftoppm", "-png", "-r", "180", "-f", "1", "-l", "5", pdf_path, tmp_prefix], stderr=subprocess.STDOUT, text=True, timeout=60)
        chunks = []
        for name in sorted(os.listdir(DOCUMENTS_DIR)):
            if not name.startswith("_ocr_tmp_page") or not name.endswith(".png"):
                continue
            img_path = os.path.join(DOCUMENTS_DIR, name)
            try:
                text = subprocess.check_output(["tesseract", img_path, "stdout"], stderr=subprocess.STDOUT, text=True, timeout=60)
                if text.strip():
                    chunks.append(f"--- {name} ---\n{text.strip()}")
            finally:
                try:
                    os.remove(img_path)
                except Exception:
                    pass
        text = "\n\n".join(chunks).strip()
        if not text:
            return {"ok": False, "mode": "no_text", "message": "OCR ran, but no text was detected."}
        with open(ocr_txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "mode": "ocr", "path": ocr_txt_path, "chars": len(text)}
    except Exception as e:
        return {"ok": False, "mode": "ocr_error", "message": str(e)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path in ("/scan", "/scan.html"):
            try:
                with open(os.path.join(_project_root, "scan.html"), "r", encoding="utf-8") as f:
                    scan_html = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(scan_html.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Could not load scan.html: {e}".encode("utf-8"))
            return
        if path == "/" or path == "/index.html" or not path.startswith("/chat"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/save_pdf":
            self._handle_save_pdf()
            return
        if path != "/chat":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            data = json.loads(body) if body else {}
            msg = (data.get("message") or "").strip()
        except Exception:
            msg = ""
        if not msg:
            self._send_json({"response": "Empty message."})
            return
        if msg.lower() in ("exit", "quit"):
            self._send_json({"response": "Say exit only in the terminal to close the server. Here, just keep chatting."})
            return
        global _chat_messages
        try:
            response, _chat_messages = process_turn(msg, _chat_messages)
            self._send_json({"response": response})
        except Exception as e:
            self._send_json({"response": f"Error: {e}", "error": str(e)})

    def _handle_save_pdf(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 25 * 1024 * 1024:
            self._send_json({"ok": False, "error": "PDF is too large. Try fewer/smaller images."}, status=413)
            return
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            data = json.loads(raw) if raw else {}
            filename = safe_filename(data.get("filename") or "scan.pdf")
            pdf_base64 = data.get("pdf_base64") or ""
            pdf_bytes = base64.b64decode(pdf_base64, validate=True)
        except Exception as e:
            self._send_json({"ok": False, "error": f"Invalid PDF upload: {e}"}, status=400)
            return
        if not pdf_bytes.startswith(b"%PDF"):
            self._send_json({"ok": False, "error": "Uploaded file does not look like a PDF."}, status=400)
            return
        os.makedirs(DOCUMENTS_DIR, exist_ok=True)
        out_path = os.path.join(DOCUMENTS_DIR, filename)
        base, ext = os.path.splitext(filename)
        counter = 2
        while os.path.exists(out_path):
            filename = f"{base}_{counter}{ext}"
            out_path = os.path.join(DOCUMENTS_DIR, filename)
            counter += 1
        try:
            with open(out_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as e:
            self._send_json({"ok": False, "error": f"Could not save PDF: {e}"}, status=500)
            return
        ocr = try_local_ocr(out_path)
        self._send_json({
            "ok": True,
            "filename": filename,
            "path": f"data/documents/{filename}",
            "ask_url": f"/?ask_doc={filename}",
            "ocr": ocr,
            "message": f"Saved to data/documents/{filename}"
        })

    def _send_json(self, obj, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    try_port = PORT
    try:
        server = HTTPServer((HOST, try_port), Handler)
        if HOST == "127.0.0.1":
            print(f"First AI Agent — open http://localhost:{try_port} in your browser.")
            print(f"Scanner — open http://localhost:{try_port}/scan")
        else:
            print(f"First AI Agent — running on port {try_port}. Use your deployment URL (e.g. Render dashboard).")
            print("Scanner route: /scan")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
        return
    except OSError as e:
        if e.errno == 48 and HOST == "127.0.0.1":
            for attempt in range(1, 10):
                try_port = PORT + attempt
                try:
                    server = HTTPServer((HOST, try_port), Handler)
                    print(f"First AI Agent — open http://localhost:{try_port} in your browser.")
                    print(f"Scanner — open http://localhost:{try_port}/scan")
                    server.serve_forever()
                    return
                except OSError:
                    continue
        print(f"Could not bind. Stop the other server or use: lsof -i :{PORT}")
        raise


if __name__ == "__main__":
    main()
