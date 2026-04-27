#!/usr/bin/env python3
"""
Minimal web UI for the agent. No IDE or terminal needed after starting.
Run: python run_web.py   (or double-click run_web.command on Mac)
Then open: http://localhost:8765
Uses only stdlib (no Flask). Stays local, no internet (unless you use an API backend).
"""
import base64
import html
import json
import re
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote

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

try:
    from src.doc_intelligence import build_document_card
except Exception:
    build_document_card = None

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

PWA_HEAD = """
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/icon.svg">
  <meta name="theme-color" content="#1a1b26">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="AI Scanner">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
"""

PWA_SCRIPT = """
<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
  }
</script>
"""

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/icon.svg">
  <meta name="theme-color" content="#1a1b26">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="AI Scanner">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
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
  </style>
</head>
<body>
  <h1>First AI Agent</h1>
  <p class="sub">Local docs &amp; Q&A. Type <strong>help</strong> for commands.</p>
  <div class="toolbar">
    <a class="linkbtn primary" href="/scan">Scan photos to PDF</a>
    <a class="linkbtn" href="/dashboard">Dashboard</a>
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
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
      });
    }
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


def inject_pwa(html_text):
    if "manifest.webmanifest" not in html_text:
        html_text = html_text.replace("</head>", PWA_HEAD + "</head>")
    if "serviceWorker" not in html_text:
        html_text = html_text.replace("</body>", PWA_SCRIPT + "</body>")
    return html_text


def get_document_rows():
    rows = []
    if not os.path.isdir(DOCUMENTS_DIR):
        return rows
    for name in sorted(os.listdir(DOCUMENTS_DIR), key=lambda n: os.path.getmtime(os.path.join(DOCUMENTS_DIR, n)), reverse=True):
        lower = name.lower()
        if lower.endswith((".ocr.txt", ".json")) or lower.startswith("_ocr_tmp_page"):
            continue
        if not lower.endswith((".pdf", ".txt", ".md", ".markdown", ".csv")):
            continue
        path = os.path.join(DOCUMENTS_DIR, name)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        ocr_path = path + ".ocr.txt"
        json_path = path + ".json"
        doc_type = "document"
        summary = ""
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                doc_type = meta.get("type") or doc_type
                s = meta.get("summary") or []
                summary = " ".join(s[:2]) if isinstance(s, list) else str(s)
            except Exception:
                pass
        elif build_document_card and (os.path.exists(ocr_path) or lower.endswith((".txt", ".md", ".markdown"))):
            try:
                meta = build_document_card(path)
                doc_type = meta.get("type") or doc_type
                s = meta.get("summary") or []
                summary = " ".join(s[:2]) if isinstance(s, list) else ""
            except Exception:
                pass
        rows.append({
            "name": name,
            "size_kb": max(1, round(stat.st_size / 1024)),
            "mtime": stat.st_mtime,
            "date": __import__("datetime").datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %I:%M %p"),
            "ocr": os.path.exists(ocr_path),
            "json": os.path.exists(json_path),
            "type": doc_type,
            "summary": summary,
        })
    return rows


def build_dashboard_html():
    rows = get_document_rows()
    cards = []
    if not rows:
        cards.append("""
        <section class='empty card'>
          <h2>No saved documents yet</h2>
          <p class='sub'>Start by scanning photos into a PDF, then tap Save to Agent.</p>
          <a class='btn primary' href='/scan'>Open Scanner</a>
        </section>
        """)
    for r in rows:
        name = html.escape(r["name"])
        qname = quote(r["name"])
        summary = html.escape(r.get("summary") or "No summary yet. OCR or document intelligence can improve this.")
        badges = []
        badges.append(f"<span>{html.escape(r['type'])}</span>")
        badges.append("<span>OCR</span>" if r["ocr"] else "<span class='mutedBadge'>No OCR</span>")
        badges.append("<span>Smart card</span>" if r["json"] else "<span class='mutedBadge'>No card</span>")
        cards.append(f"""
        <article class='doc card' data-name='{name.lower()}'>
          <div class='docTop'>
            <div><h2>{name}</h2><p class='sub'>{html.escape(r['date'])} · {r['size_kb']} KB</p></div>
          </div>
          <div class='badges'>{''.join(badges)}</div>
          <p class='summary'>{summary}</p>
          <div class='actions'>
            <a class='btn primary' href='/?ask_doc={qname}'>Ask AI</a>
            <a class='btn' href='/scan'>Scan More</a>
          </div>
        </article>
        """)
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>
  <link rel='manifest' href='/manifest.webmanifest'>
  <link rel='icon' href='/icon.svg' type='image/svg+xml'>
  <meta name='theme-color' content='#1a1b26'>
  <title>Document Dashboard</title>
  <style>
    *{{box-sizing:border-box}} body{{margin:0;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:radial-gradient(circle at top,#25283a 0,#1a1b26 48%);color:#c0caf5;min-height:100vh}} main{{max-width:820px;margin:0 auto;padding:1rem 1rem 6rem}} a{{color:#7aa2f7;text-decoration:none}} .topbar{{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:calc(.75rem + env(safe-area-inset-top,0px)) 1rem .75rem;margin:0 -1rem 1rem;background:rgba(26,27,38,.9);backdrop-filter:blur(14px);border-bottom:1px solid rgba(59,66,97,.65)}} .brand small,.sub{{color:rgba(192,202,245,.76)}} h1{{font-size:1.45rem;margin:.25rem 0}} h2{{font-size:1rem;margin:.1rem 0}} .card{{background:rgba(22,22,30,.96);border:1px solid #3b4261;border-radius:20px;padding:1rem;margin:1rem 0}} input{{width:100%;padding:.9rem;border:1px solid #3b4261;border-radius:14px;background:#101014;color:#c0caf5;font-size:1rem}} .badges{{display:flex;flex-wrap:wrap;gap:.45rem;margin:.75rem 0}} .badges span{{font-size:.76rem;font-weight:800;border-radius:999px;padding:.35rem .55rem;background:#292e42;color:#9ece6a;border:1px solid #3b4261}} .badges .mutedBadge{{color:#e0af68}} .summary{{color:rgba(192,202,245,.82);line-height:1.45}} .actions{{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;margin-top:1rem}} .btn{{display:flex;align-items:center;justify-content:center;min-height:50px;border-radius:14px;background:#292e42;color:#c0caf5;border:1px solid #3b4261;font-weight:850}} .btn.primary{{background:#7aa2f7;color:#1a1b26;border:0}} .bottomNav{{position:fixed;left:0;right:0;bottom:0;z-index:20;padding:.7rem .85rem calc(.7rem + env(safe-area-inset-bottom,0px));background:rgba(22,22,30,.94);backdrop-filter:blur(16px);border-top:1px solid rgba(59,66,97,.85);display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}} .navItem{{display:flex;align-items:center;justify-content:center;min-height:48px;border-radius:14px;color:rgba(192,202,245,.76);font-size:.8rem;font-weight:800;text-decoration:none}} .navItem.active{{background:#292e42;color:#7aa2f7}}
  </style>
</head>
<body>
<main>
  <header class='topbar'><div class='brand'><small>Document Vault</small><h1>Dashboard</h1></div><a class='btn' style='padding:0 .8rem;min-height:40px' href='/scan'>Scan</a></header>
  <section class='card'><input id='search' placeholder='Search saved documents…'></section>
  {''.join(cards)}
</main>
<nav class='bottomNav'><a class='navItem' href='/'>Agent</a><a class='navItem' href='/scan'>Scan</a><a class='navItem active' href='/dashboard'>Dashboard</a></nav>
<script>
const search=document.getElementById('search');
if(search) search.addEventListener('input',()=>{{const q=search.value.toLowerCase();document.querySelectorAll('.doc').forEach(c=>c.style.display=c.dataset.name.includes(q)?'block':'none')}});
if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{{}}));
</script>
</body></html>"""


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
    def _serve_file(self, filename, content_type):
        try:
            with open(os.path.join(_project_root, filename), "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Not found: {filename} ({e})".encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/manifest.webmanifest":
            self._serve_file("manifest.webmanifest", "application/manifest+json; charset=utf-8")
            return
        if path == "/sw.js":
            self._serve_file("sw.js", "application/javascript; charset=utf-8")
            return
        if path == "/icon.svg":
            self._serve_file("icon.svg", "image/svg+xml; charset=utf-8")
            return
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(build_dashboard_html().encode("utf-8"))
            return
        if path in ("/scan", "/scan.html"):
            try:
                with open(os.path.join(_project_root, "scan.html"), "r", encoding="utf-8") as f:
                    scan_html = inject_pwa(f.read())
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
            "dashboard_url": "/dashboard",
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
            print(f"Dashboard — open http://localhost:{try_port}/dashboard")
            print("PWA files — /manifest.webmanifest /sw.js /icon.svg")
        else:
            print(f"First AI Agent — running on port {try_port}. Use your deployment URL (e.g. Render dashboard).")
            print("Scanner route: /scan")
            print("Dashboard route: /dashboard")
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
                    print(f"Dashboard — open http://localhost:{try_port}/dashboard")
                    print("PWA files — /manifest.webmanifest /sw.js /icon.svg")
                    server.serve_forever()
                    return
                except OSError:
                    continue
        print(f"Could not bind. Stop the other server or use: lsof -i :{PORT}")
        raise


if __name__ == "__main__":
    main()
