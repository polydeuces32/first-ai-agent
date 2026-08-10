"""Legal, support, and compliance pages required for App Store and trust."""

from __future__ import annotations

import os
from typing import Set

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal"])

PUBLIC_LEGAL_PATHS: Set[str] = {
    "/privacy",
    "/support",
    "/terms",
    "/health-disclaimer",
    "/app",
}

SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@evidenceos.app")
PRIVACY_EMAIL = os.getenv("PRIVACY_EMAIL", SUPPORT_EMAIL)
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "").rstrip("/") or "https://evidenceos.app"

_LEGAL_STYLE = """
  :root{--bg:#0a0b0f;--panel:#12141c;--line:#23262f;--fg:#e7e9ee;--muted:#9aa0ad;--accent:#3ddc97;--accent2:#5b8cff;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif;}
  a{color:var(--accent2);text-decoration:none}
  .wrap{max-width:760px;margin:0 auto;padding:32px 20px 80px}
  .brand{display:flex;align-items:center;gap:10px;font-weight:700;margin-bottom:28px}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--accent)}
  h1{font-size:32px;line-height:1.1;margin:0 0 8px}
  h2{font-size:20px;margin:28px 0 8px}
  p,li{color:#cfd3dc}
  .muted{color:var(--muted);font-size:14px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;margin:20px 0}
  .nav{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0 0;font-size:14px}
  .pill{display:inline-block;background:rgba(61,220,151,.12);color:var(--accent);padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700}
"""


def _legal_page(title: str, body_html: str) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — EvidenceOS</title>
<style>{_LEGAL_STYLE}</style></head><body><div class="wrap">
  <div class="brand"><span class="dot"></span><a href="/try">EvidenceOS</a></div>
  <h1>{title}</h1>
  {body_html}
  <div class="nav">
    <a href="/try">Try demo</a>
    <a href="/privacy">Privacy</a>
    <a href="/support">Support</a>
    <a href="/terms">Terms</a>
    <a href="/health-disclaimer">Health disclaimer</a>
    <a href="/app">iOS app</a>
  </div>
</div></body></html>"""


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page() -> HTMLResponse:
    body = f"""
  <p class="muted">Last updated: June 2026</p>
  <div class="card">
    <p>EvidenceOS helps you ask questions about documents using <b>verified citations only</b>.
    If no supporting evidence is found, the system refuses to answer instead of guessing.</p>
    <h2>What we collect</h2>
    <ul>
      <li><b>Demo usage:</b> text you paste, questions you ask, and generated answers with citations.</li>
      <li><b>Share links:</b> if you create a share card, we store the question, answer, citations, and timestamp.</li>
      <li><b>Technical logs:</b> IP address (for rate limiting), request metadata, and error logs.</li>
      <li><b>Uploaded documents (workspace mode):</b> filename, extracted text, and index metadata when you use document upload features.</li>
    </ul>
    <h2>What we do not do</h2>
    <ul>
      <li>We do not sell your personal data.</li>
      <li>We do not use your document content to train third-party AI models.</li>
      <li>We do not provide medical, legal, or financial advice.</li>
    </ul>
    <h2>How data is used</h2>
    <ul>
      <li>To answer your questions from the document you provide.</li>
      <li>To generate shareable verification cards when you choose to share.</li>
      <li>To protect the service (rate limits, abuse prevention, reliability).</li>
    </ul>
    <h2>Retention</h2>
    <p>Demo share cards and audit events may be retained for a limited period for reliability and abuse prevention.
    Production retention windows should be configured per deployment policy.</p>
    <h2>Your choices</h2>
    <ul>
      <li>You can use the public demo without creating an account.</li>
      <li>You can avoid sharing result links if you do not want answers stored.</li>
      <li>Contact us to request deletion of data associated with your use where applicable.</li>
    </ul>
    <h2>Contact</h2>
    <p>Privacy questions: <a href="mailto:{PRIVACY_EMAIL}">{PRIVACY_EMAIL}</a></p>
  </div>"""
    return HTMLResponse(_legal_page("Privacy Policy", body))


@router.get("/support", response_class=HTMLResponse)
def support_page() -> HTMLResponse:
    body = f"""
  <div class="card">
    <p>Need help with EvidenceOS? We're here.</p>
    <h2>Contact</h2>
    <p>Email: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>
    <h2>Common questions</h2>
    <ul>
      <li><b>Why did EvidenceOS refuse to answer?</b> No supporting sentence was found in your document. That is intentional.</li>
      <li><b>Is this medical or legal advice?</b> No. It is informational document Q&amp;A with citations. See <a href="/health-disclaimer">health disclaimer</a>.</li>
      <li><b>Where is my data processed?</b> Depends on deployment. The public demo may use a hosted backend. See <a href="/privacy">privacy policy</a>.</li>
      <li><b>iOS app issues?</b> See <a href="/app">iOS app info</a> or email support with your iOS version and steps to reproduce.</li>
    </ul>
    <h2>Status</h2>
    <p>Service health: <a href="/health">/health</a> · Readiness: <a href="/ready">/ready</a></p>
  </div>"""
    return HTMLResponse(_legal_page("Support", body))


@router.get("/terms", response_class=HTMLResponse)
def terms_page() -> HTMLResponse:
    body = """
  <p class="muted">Last updated: June 2026</p>
  <div class="card">
    <p>By using EvidenceOS, you agree to these terms.</p>
    <h2>Service description</h2>
    <p>EvidenceOS provides evidence-verified document question answering. Answers are extractive citations from
    the text you supply, or the system abstains.</p>
    <h2>No professional advice</h2>
    <p>EvidenceOS does not provide medical, legal, tax, or financial advice. Outputs are informational only.
    Consult qualified professionals before making decisions.</p>
    <h2>Your content</h2>
    <p>You are responsible for the documents and questions you submit. Do not upload content you do not have
    the right to use.</p>
    <h2>Availability</h2>
    <p>The service is provided as-is. We may modify, suspend, or discontinue features with reasonable notice
    where practical.</p>
    <h2>Limitation of liability</h2>
    <p>To the maximum extent permitted by law, EvidenceOS is not liable for decisions made based on cited outputs.
    Always verify citations against the original source document.</p>
  </div>"""
    return HTMLResponse(_legal_page("Terms of Use", body))


@router.get("/health-disclaimer", response_class=HTMLResponse)
def health_disclaimer_page() -> HTMLResponse:
    body = """
  <div class="card">
    <span class="pill">NOT MEDICAL ADVICE</span>
    <h2>Purpose</h2>
    <p>Health-related examples in EvidenceOS (including diabetes and clinical study demos) are for
    <b>educational demonstration only</b>. They cite public-health sources such as CDC and NIH where noted.</p>
    <h2>What EvidenceOS is not</h2>
    <ul>
      <li>Not a medical device</li>
      <li>Not a diagnostic tool</li>
      <li>Not a substitute for a doctor or licensed clinician</li>
      <li>Not an emergency service</li>
    </ul>
    <h2>What you should do</h2>
    <ul>
      <li>Talk to a qualified healthcare professional about your health.</li>
      <li>Verify any cited sentence against the original source.</li>
      <li>Do not delay care because of an EvidenceOS output.</li>
    </ul>
    <h2>Emergencies</h2>
    <p>If you think you have a medical emergency, call your local emergency number immediately.</p>
  </div>"""
    return HTMLResponse(_legal_page("Health Disclaimer", body))


@router.get("/app", response_class=HTMLResponse)
def ios_app_page() -> HTMLResponse:
    body = f"""
  <div class="card">
    <span class="pill">iOS</span>
    <h2>EvidenceOS for iPhone</h2>
    <p>The iOS app wraps the EvidenceOS verified demo with native document import and sharing.
    It connects to the hosted EvidenceOS service at <a href="{PUBLIC_SITE_URL}">{PUBLIC_SITE_URL}</a>.</p>
    <h2>Native features</h2>
    <ul>
      <li>Import text from Files / iCloud</li>
      <li>Ask questions with cited answers or refusal</li>
      <li>Share verified result cards</li>
      <li>Privacy and health disclaimers in-app</li>
    </ul>
    <h2>Data processing note</h2>
    <p>Unless you self-host, pasted document text and questions may be processed by the hosted backend
    to generate cited answers. See <a href="/privacy">privacy policy</a>.</p>
    <h2>Support</h2>
    <p><a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>
  </div>"""
    return HTMLResponse(_legal_page("iOS App", body))
