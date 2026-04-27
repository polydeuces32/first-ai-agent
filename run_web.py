#!/usr/bin/env python3
"""First AI Agent mobile web server.

Routes:
- /              Agent chat
- /scan          Mobile scanner PWA
- /dashboard     Saved document dashboard
- /preview?file=NAME
- /raw?file=NAME
- /download?file=NAME
- /save_pdf      Save generated PDF into data/documents/
- /delete_doc    Delete a saved document and sidecars
"""
import base64
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote, unquote, urlparse

_project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _project_root)
os.chdir(_project_root)
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

try:
    PORT = int(os.environ.get("PORT") or 8765)
except (TypeError, ValueError):
    PORT = 8765
HOST = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
DOCUMENTS_DIR = os.path.join(_project_root, "data", "documents")
os.makedirs(DOCUMENTS_DIR, exist_ok=True)
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
if ('serviceWorker' in navigator) window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));
</script>
"""


def safe_filename(name):
    name = (name or "scan.pdf").strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name or "scan.pdf"


def safe_doc_path(name):
    name = safe_filename(unquote(name or ""))
    path = os.path.abspath(os.path.join(DOCUMENTS_DIR, name))
    root = os.path.abspath(DOCUMENTS_DIR)
    if not path.startswith(root + os.sep):
        return None
    return path


def inject_pwa(text):
    if "manifest.webmanifest" not in text:
        text = text.replace("</head>", PWA_HEAD + "</head>")
    if "serviceWorker" not in text:
        text = text.replace("</body>", PWA_SCRIPT + "</body>")
    return text


def extract_pdf_text_if_any(path):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(path)
        parts = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(txt.strip())
        return "\n\n".join(parts).strip()
    except Exception:
        return ""


def try_local_ocr(pdf_path):
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
                txt = subprocess.check_output(["tesseract", img_path, "stdout"], stderr=subprocess.STDOUT, text=True, timeout=60)
                if txt.strip():
                    chunks.append(f"--- {name} ---\n{txt.strip()}")
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


def document_rows():
    rows = []
    for name in sorted(os.listdir(DOCUMENTS_DIR), key=lambda n: os.path.getmtime(os.path.join(DOCUMENTS_DIR, n)), reverse=True):
        lower = name.lower()
        if lower.startswith("_ocr_tmp_page") or lower.endswith((".ocr.txt", ".json")):
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
        summary = "No summary yet. OCR or document intelligence can improve this."
        if os.path.exists(json_path):
            try:
                meta = json.load(open(json_path, "r", encoding="utf-8"))
                doc_type = meta.get("type") or doc_type
                s = meta.get("summary") or []
                summary = " ".join(s[:2]) if isinstance(s, list) and s else summary
            except Exception:
                pass
        elif build_document_card and (os.path.exists(ocr_path) or lower.endswith((".txt", ".md", ".markdown"))):
            try:
                meta = build_document_card(path)
                doc_type = meta.get("type") or doc_type
                s = meta.get("summary") or []
                summary = " ".join(s[:2]) if isinstance(s, list) and s else summary
            except Exception:
                pass
        rows.append({
            "name": name,
            "date": datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %I:%M %p"),
            "size_kb": max(1, round(stat.st_size / 1024)),
            "ocr": os.path.exists(ocr_path),
            "json": os.path.exists(json_path),
            "type": doc_type,
            "summary": summary,
        })
    return rows


def app_shell_css():
    return """
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:radial-gradient(circle at top,#25283a 0,#1a1b26 48%);color:#c0caf5;min-height:100vh}main{max-width:820px;margin:0 auto;padding:1rem 1rem 6rem}a{color:#7aa2f7;text-decoration:none}.topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;padding:calc(.75rem + env(safe-area-inset-top,0px)) 1rem .75rem;margin:0 -1rem 1rem;background:rgba(26,27,38,.92);backdrop-filter:blur(14px);border-bottom:1px solid #3b4261}h1{font-size:1.45rem;margin:.2rem 0}h2{font-size:1rem;margin:.1rem 0}.sub{color:rgba(192,202,245,.76)}.card{background:rgba(22,22,30,.96);border:1px solid #3b4261;border-radius:20px;padding:1rem;margin:1rem 0}input{width:100%;padding:.9rem;border:1px solid #3b4261;border-radius:14px;background:#101014;color:#c0caf5;font-size:1rem}.badges{display:flex;flex-wrap:wrap;gap:.45rem;margin:.75rem 0}.badges span{font-size:.76rem;font-weight:800;border-radius:999px;padding:.35rem .55rem;background:#292e42;color:#9ece6a;border:1px solid #3b4261}.summary{color:rgba(192,202,245,.82);line-height:1.45}.actions{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;margin-top:1rem}.btn{display:flex;align-items:center;justify-content:center;min-height:50px;border-radius:14px;background:#292e42;color:#c0caf5;border:1px solid #3b4261;font-weight:850;text-align:center}button.btn{width:100%;font:inherit;cursor:pointer}.btn.primary{background:#7aa2f7;color:#1a1b26;border:0}.btn.danger{background:#f7768e;color:#1a1b26;border:0}.bottomNav{position:fixed;left:0;right:0;bottom:0;z-index:20;padding:.7rem .85rem calc(.7rem + env(safe-area-inset-bottom,0px));background:rgba(22,22,30,.94);backdrop-filter:blur(16px);border-top:1px solid #3b4261;display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem}.navItem{display:flex;align-items:center;justify-content:center;min-height:48px;border-radius:14px;color:rgba(192,202,245,.76);font-size:.8rem;font-weight:800;text-decoration:none}.navItem.active{background:#292e42;color:#7aa2f7}.previewFrame{width:100%;height:72vh;border:1px solid #3b4261;border-radius:18px;background:#101014}.preText{white-space:pre-wrap;line-height:1.5;background:#101014;border:1px solid #3b4261;border-radius:18px;padding:1rem;overflow:auto;max-height:72vh}
"""


def agent_html():
    return f"""<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>{PWA_HEAD}<title>First AI Agent</title><style>{app_shell_css()}#log{{background:#16161e;border:1px solid #3b4261;border-radius:18px;padding:1rem;min-height:220px;max-height:52vh;overflow:auto;white-space:pre-wrap;word-break:break-word}}.msg{{margin-bottom:.75rem}}.msg.user{{color:#7aa2f7}}.msg.agent{{color:#9ece6a}}form{{display:flex;gap:.5rem;margin-top:.75rem}}form input{{flex:1}}form button{{min-width:84px}}</style></head><body><main><header class='topbar'><div><small class='sub'>Local Document AI</small><h1>First AI Agent</h1></div><a class='btn' style='padding:0 .8rem;min-height:40px' href='/scan'>Scan</a></header><section class='card'><p class='sub'>Ask questions about saved PDFs, OCR text, notes, CSV files, and local documents.</p><div class='actions'><a class='btn primary' href='/scan'>Scan Photos to PDF</a><a class='btn' href='/dashboard'>Dashboard</a></div></section><section class='card'><div id='log'></div><form id='f'><input id='input' placeholder='Ask or type help…' autocomplete='off'><button class='btn primary' type='submit'>Send</button></form></section></main><nav class='bottomNav'><a class='navItem active' href='/'>Agent</a><a class='navItem' href='/scan'>Scan</a><a class='navItem' href='/dashboard'>Dashboard</a></nav><script>
const log=document.getElementById('log'),input=document.getElementById('input'),f=document.getElementById('f');
function add(msg,who){{const d=document.createElement('div');d.className='msg '+who;d.textContent=(who==='user'?'You: ':'Agent: ')+msg;log.appendChild(d);log.scrollTop=log.scrollHeight;}}
async function sendMessage(text){{if(!text)return;add(text,'user');try{{const r=await fetch('/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:text}})}});const j=await r.json();add(j.response||j.error||'No response','agent');}}catch(e){{add('Server error. Restart run_web.py and try again.','agent');}}}}
const params=new URLSearchParams(location.search);const askDoc=params.get('ask_doc');if(askDoc)sendMessage('read '+askDoc);
f.addEventListener('submit',e=>{{e.preventDefault();const text=input.value.trim();if(!text)return;input.value='';sendMessage(text);}});
if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{{}}));
</script></body></html>"""


def dashboard_html():
    rows = document_rows()
    cards = []
    if not rows:
        cards.append("""<section class='card'><h2>No saved documents yet</h2><p class='sub'>Start by scanning photos into a PDF, then tap Save to Agent.</p><a class='btn primary' href='/scan'>Open Scanner</a></section>""")
    for r in rows:
        name = html.escape(r["name"])
        qname = quote(r["name"])
        summary = html.escape(r["summary"])
        cards.append(f"""
<article class='doc card' data-name='{name.lower()}'>
  <h2>{name}</h2>
  <p class='sub'>{html.escape(r['date'])} · {r['size_kb']} KB</p>
  <div class='badges'><span>{html.escape(r['type'])}</span><span>{'OCR' if r['ocr'] else 'No OCR'}</span><span>{'Smart card' if r['json'] else 'No card'}</span></div>
  <p class='summary'>{summary}</p>
  <div class='actions'>
    <a class='btn primary' href='/preview?file={qname}'>Preview</a>
    <a class='btn' href='/?ask_doc={qname}'>Ask AI</a>
    <a class='btn' href='/download?file={qname}'>Download</a>
    <button class='btn shareBtn' data-file='{name}'>Share</button>
    <button class='btn danger deleteBtn' data-file='{name}'>Delete</button>
  </div>
</article>""")
    return f"""<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>{PWA_HEAD}<title>Document Dashboard</title><style>{app_shell_css()}</style></head><body><main><header class='topbar'><div><small class='sub'>Document Vault</small><h1>Dashboard</h1></div><a class='btn' style='padding:0 .8rem;min-height:40px' href='/scan'>Scan</a></header><section class='card'><input id='search' placeholder='Search saved documents…'></section>{''.join(cards)}</main><nav class='bottomNav'><a class='navItem' href='/'>Agent</a><a class='navItem' href='/scan'>Scan</a><a class='navItem active' href='/dashboard'>Dashboard</a></nav><script>
const search=document.getElementById('search');if(search)search.addEventListener('input',()=>{{const q=search.value.toLowerCase();document.querySelectorAll('.doc').forEach(c=>c.style.display=c.dataset.name.includes(q)?'block':'none')}});
document.querySelectorAll('.deleteBtn').forEach(btn=>btn.addEventListener('click',async()=>{{const file=btn.dataset.file;if(!confirm('Delete '+file+' and related OCR/metadata files?'))return;const r=await fetch('/delete_doc',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{file}})}});const j=await r.json();if(j.ok)location.reload();else alert(j.error||'Delete failed');}}));
document.querySelectorAll('.shareBtn').forEach(btn=>btn.addEventListener('click',async()=>{{const file=btn.dataset.file;const url='/download?file='+encodeURIComponent(file);try{{if(navigator.share){{await navigator.share({{title:file,text:'Document from First AI Agent',url:location.origin+url}});}}else location.href=url;}}catch(e){{if(e.name!=='AbortError')location.href=url;}}}}));
if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{{}}));
</script></body></html>"""


def preview_html(name, doc_path):
    safe_name = html.escape(os.path.basename(doc_path))
    qname = quote(os.path.basename(doc_path))
    lower = doc_path.lower()
    if lower.endswith(".pdf"):
        content = f"<iframe class='previewFrame' src='/raw?file={qname}' title='Preview {safe_name}'></iframe>"
    elif lower.endswith((".txt", ".md", ".markdown", ".csv")):
        try:
            text = open(doc_path, "r", encoding="utf-8", errors="ignore").read()[:120000]
        except Exception as e:
            text = f"Could not read file: {e}"
        content = f"<div class='preText'>{html.escape(text)}</div>"
    else:
        content = "<section class='card'><p class='sub'>Preview is not available for this file type. Download it instead.</p></section>"
    ocr_path = doc_path + ".ocr.txt"
    ocr_link = f"<a class='btn' href='/preview?file={quote(os.path.basename(ocr_path))}'>View OCR Text</a>" if os.path.exists(ocr_path) else ""
    return f"""<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>{PWA_HEAD}<title>Preview {safe_name}</title><style>{app_shell_css()}</style></head><body><main><header class='topbar'><div><small class='sub'>Preview</small><h1>{safe_name}</h1></div><a class='btn' style='padding:0 .8rem;min-height:40px' href='/dashboard'>Back</a></header><section class='card'><div class='actions'><a class='btn primary' href='/?ask_doc={qname}'>Ask AI</a><a class='btn' href='/download?file={qname}'>Download</a>{ocr_link}</div></section>{content}</main><nav class='bottomNav'><a class='navItem' href='/'>Agent</a><a class='navItem' href='/scan'>Scan</a><a class='navItem active' href='/dashboard'>Dashboard</a></nav>{PWA_SCRIPT}</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _serve_file(self, filename, content_type):
        path = os.path.join(_project_root, filename)
        try:
            data = open(path, "rb").read()
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

    def _serve_document(self, doc_path, attachment=False):
        ctype = mimetypes.guess_type(doc_path)[0] or "application/octet-stream"
        data = open(doc_path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if attachment:
            self.send_header("Content-Disposition", f"attachment; filename=\"{os.path.basename(doc_path)}\"")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/manifest.webmanifest": return self._serve_file("manifest.webmanifest", "application/manifest+json; charset=utf-8")
        if path == "/sw.js": return self._serve_file("sw.js", "application/javascript; charset=utf-8")
        if path == "/icon.svg": return self._serve_file("icon.svg", "image/svg+xml; charset=utf-8")
        if path == "/health":
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(b"ok"); return
        if path in ("/download", "/raw", "/preview"):
            name = parse_qs(parsed.query).get("file", [""])[0]
            doc_path = safe_doc_path(name)
            if not doc_path or not os.path.isfile(doc_path):
                self.send_response(404); self.end_headers(); return
            if path == "/download": return self._serve_document(doc_path, attachment=True)
            if path == "/raw": return self._serve_document(doc_path, attachment=False)
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(preview_html(name, doc_path).encode("utf-8")); return
        if path == "/dashboard":
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(dashboard_html().encode("utf-8")); return
        if path in ("/scan", "/scan.html"):
            try:
                scan = inject_pwa(open(os.path.join(_project_root, "scan.html"), "r", encoding="utf-8").read())
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(scan.encode("utf-8"))
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode("utf-8"))
            return
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(agent_html().encode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/delete_doc":
            length = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(length).decode("utf-8", errors="ignore")
            try:
                name = json.loads(raw).get("file", "")
                doc_path = safe_doc_path(name)
                if not doc_path or not os.path.isfile(doc_path):
                    return self._json({"ok": False, "error": "File not found"}, 404)
                deleted = []
                for p in [doc_path, doc_path + ".ocr.txt", doc_path + ".json"]:
                    if os.path.exists(p):
                        os.remove(p); deleted.append(os.path.basename(p))
                return self._json({"ok": True, "deleted": deleted})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 400)
        if path == "/save_pdf": return self._handle_save_pdf()
        if path != "/chat":
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            msg = (json.loads(body).get("message") or "").strip()
        except Exception:
            msg = ""
        if not msg: return self._json({"response": "Empty message."})
        global _chat_messages
        try:
            response, _chat_messages = process_turn(msg, _chat_messages)
            return self._json({"response": response})
        except Exception as e:
            return self._json({"response": f"Error: {e}", "error": str(e)})

    def _handle_save_pdf(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 25 * 1024 * 1024:
            return self._json({"ok": False, "error": "PDF is too large. Try fewer/smaller images."}, 413)
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            data = json.loads(raw) if raw else {}
            filename = safe_filename(data.get("filename") or "scan.pdf")
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            pdf_bytes = base64.b64decode(data.get("pdf_base64") or "", validate=True)
        except Exception as e:
            return self._json({"ok": False, "error": f"Invalid PDF upload: {e}"}, 400)
        if not pdf_bytes.startswith(b"%PDF"):
            return self._json({"ok": False, "error": "Uploaded file does not look like a PDF."}, 400)
        out_path = os.path.join(DOCUMENTS_DIR, filename)
        base, ext = os.path.splitext(filename); counter = 2
        while os.path.exists(out_path):
            filename = f"{base}_{counter}{ext}"; out_path = os.path.join(DOCUMENTS_DIR, filename); counter += 1
        try:
            open(out_path, "wb").write(pdf_bytes)
        except Exception as e:
            return self._json({"ok": False, "error": f"Could not save PDF: {e}"}, 500)
        ocr = try_local_ocr(out_path)
        return self._json({"ok": True, "filename": filename, "path": f"data/documents/{filename}", "ask_url": f"/?ask_doc={filename}", "download_url": f"/download?file={quote(filename)}", "preview_url": f"/preview?file={quote(filename)}", "ocr": ocr, "dashboard_url": "/dashboard", "message": f"Saved to data/documents/{filename}"})

    def log_message(self, *_):
        pass


def main():
    try:
        server = HTTPServer((HOST, PORT), Handler)
    except OSError:
        server = HTTPServer((HOST, PORT + 1), Handler)
    actual = server.server_port
    print(f"First AI Agent — open http://localhost:{actual}")
    print(f"Scanner — open http://localhost:{actual}/scan")
    print(f"Dashboard — open http://localhost:{actual}/dashboard")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
