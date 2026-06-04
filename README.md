# EvidenceOS

EvidenceOS is a local-first FastAPI document intelligence system that lets users:

- upload documents
- ask grounded questions with citations
- generate safe risk reviews
- inspect audit logs
- run smoke checks
- deploy with Docker for SaaS-style hosting

The system is designed around one rule:

> No evidence, no answer. No verified citation, no risk finding.

## Core product loop

1. Upload a TXT, MD, CSV, or PDF document
2. Extract text locally
3. Ask a question and get a cited answer
4. Run a risk review with an approval gate for high-risk workflows
5. Inspect the health/readiness endpoints
6. Deploy the same app behind Docker when ready for SaaS hosting

## Key endpoints

- `GET /`
- `GET /health`
- `GET /ready`
- `GET /demo`
- `GET /tools`
- `GET /documents`
- `POST /documents/upload`
- `POST /documents/{document_id}/ask`
- `POST /documents/{document_id}/review`
- `GET /evals/smoke`

## Local development

Use the backend virtual environment if it already exists:

```bash
cd ~/first-ai-agent/backend
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then use the CLI-style UI or terminal client:

```txt
# Browser: open evidenceos.html (green terminal, type: help)
# Terminal:
cd ~/first-ai-agent/backend
./evidenceos_cli.py repl
# or double-click evidenceos.command from repo root
```

## Smoke checks

```bash
cd ~/first-ai-agent/backend
./.venv/bin/python -m pytest tests/test_smoke.py -q
```

## Production deployment

This repo now includes a Render blueprint for production deployment:

- `Dockerfile` for the app image
- `render.yaml` for the web service + managed Postgres
- `/health` for health checks
- `/ready` for readiness checks

Deploy flow on Render:

1. Push this repo to GitHub
2. Create a new Render Blueprint
3. Point it at `render.yaml`
4. Let Render provision the web service and Postgres database
5. Set any production CORS origins in the Render dashboard if you add a separate frontend later

Recommended production settings:

- `APP_ENV=production`
- `DATABASE_URL` from managed Postgres
- `UPLOAD_DIR=/var/data/uploads` on the persistent disk
- `MAX_UPLOAD_BYTES` matched to your plan
- `LOG_LEVEL=INFO`
- `DB_POOL_SIZE=5`
- `DB_MAX_OVERFLOW=10`
- `DB_POOL_RECYCLE_SECONDS=1800`
- `DB_POOL_TIMEOUT_SECONDS=30`

Recommended first SaaS target:
- Render
- then Railway or Fly.io if you want a different hosting model

Use the included `Dockerfile` as the deployment entrypoint.

## Docker build

Build the production container from the repo root:

```bash
cd ~/first-ai-agent
docker build -t evidenceos:local .
```

Run it locally:

```bash
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=sqlite:///./agentops.db \
  -e APP_ENV=production \
  evidenceos:local
```

## Environment variables

Copy `.env.example` to `.env` and adjust as needed.

## Security stance

- local CORS is restricted by default
- high-risk document/report workflows require approval
- unsupported file types are rejected
- uploads are size-limited
- the app does not expose arbitrary shell execution

## Semantic index (NPU-ready)

EvidenceOS builds a **local semantic index** on every upload so `/ask` can use hybrid citations (semantic + keyword).

**Check status (no auth required):**

```bash
curl http://127.0.0.1:8000/inference/health
```

**User flow:** upload → wait for `index_status: ready` in the response → ask questions. Open `evidenceos.html` in a browser (or Live Server on port 5500) to see accelerator status.

**Backends** (`INFERENCE_BACKEND` in `.env`):

| Value | Meaning |
|-------|---------|
| `auto` | hash, or sentence-transformers if installed, Core ML when bundle exists |
| `hash` | lightweight CPU index (default in CI, no downloads) |
| `sentence` | better embeddings via `pip install -r requirements-inference.txt` |
| `coreml` | Apple Neural Engine path (requires Core ML embed bundle; falls back until added) |
| `none` | disable semantic index |

Reindex: `POST /documents/{document_id}/reindex`

## What to improve next

- persistent user auth
- document search
- stronger citation formatting
- async job queue for long documents
- S3 storage for uploads
- Postgres in production
- SaaS billing and tenant separation
