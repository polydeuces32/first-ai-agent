#!/usr/bin/env python3
"""
Minimal web UI for the agent. No IDE or terminal needed after starting.
Run: python run_web.py   (or double-click run_web.command on Mac)
Then open: http://localhost:8765
Uses only stdlib (no Flask). Stays local, no internet (unless you use an API backend).
"""
import json
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

# Use PORT and 0.0.0.0 when deployed (e.g. Render, Railway); localhost when local
PORT = int(os.environ.get("PORT", 8765))
HOST = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"

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
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      add(text, "user");
      input.value = "";
      try {
        const r = await fetch("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text }) });
        let j = {};
        try { j = await r.json(); } catch (_) { add("Server error (no JSON). Is the server running?", "agent"); return; }
        if (!r.ok) { add("Error " + r.status + ": " + (j.error || j.response || r.statusText), "agent"); return; }
        add(j.response || j.error || "No response", "agent");
      } catch (err) {
        add("No server. Start it first: double-click run_web.command or run .venv/bin/python run_web.py in the project folder, then open " + location.origin, "agent");
      }
    });
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/chat":
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

    def _send_json(self, obj):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def log_message(self, *_):
        pass


def main():
    try_port = PORT
    try:
        server = HTTPServer((HOST, try_port), Handler)
        if HOST == "127.0.0.1":
            print(f"First AI Agent — open http://localhost:{try_port} in your browser.")
        else:
            print(f"First AI Agent — running on port {try_port}. Use your deployment URL (e.g. Render dashboard).")
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
                    server.serve_forever()
                    return
                except OSError:
                    continue
        print(f"Could not bind. Stop the other server or use: lsof -i :{PORT}")
        raise


if __name__ == "__main__":
    main()
