# LLM backends (alternatives to Ollama)

The agent can use **Ollama**, any **OpenAI-compatible API**, or **no LLM** (offline, no model, no internet, minimal CPU).

---

## 1. Ollama (default, local)

Run Ollama, then the agent:

```bash
ollama serve   # or open the Ollama app
# In another terminal:
python -m src.agent
```

Env (optional): `OLLAMA_URL`, `OLLAMA_MODEL`

---

## 2. LM Studio (local, no Ollama)

Run models in [LM Studio](https://lmstudio.ai/); it exposes an OpenAI-compatible API on port 1234.

1. Install LM Studio, load a model, start the local server (e.g. "Start Server" in the app).
2. Run the agent:

```bash
export LLM_BACKEND=openai
export OPENAI_BASE_URL=http://localhost:1234/v1
export OPENAI_MODEL=llama-3-8b   # or whatever model you loaded
python -m src.agent
```

No API key needed for local LM Studio.

---

## 3. Groq (cloud, free tier)

[Groq](https://groq.com/) has a free tier and is fast.

```bash
export LLM_BACKEND=openai
export OPENAI_BASE_URL=https://api.groq.com/openai/v1
export OPENAI_API_KEY=gsk_xxxx   # from groq.com dashboard
export OPENAI_MODEL=llama-3.1-70b-versatile   # or llama-3.1-8b-instant
python -m src.agent
```

---

## 4. OpenAI (cloud, paid)

```bash
export LLM_BACKEND=openai
export OPENAI_API_KEY=sk-xxxx
export OPENAI_MODEL=gpt-4o-mini   # or gpt-4o
python -m src.agent
```

`OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`.

---

## 5. Other OpenAI-compatible APIs

Same pattern: set `LLM_BACKEND=openai`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` (if required), and `OPENAI_MODEL`. Works with Together, Fireworks, Azure OpenAI, local servers, etc.

---

## 6. No LLM — offline, no internet, no model (no reliance on your hardware for inference)

No server, no API, no GPU/CPU for a model. The agent only does fixed actions from simple phrases.

```bash
export LLM_BACKEND=none
python -m src.agent
```

**What works:**
- **What documents do we have** / **list documents** → lists files in `data/documents/`
- **read bitcoin.pdf** (or any filename) → extracts and shows text from that document
- **wow report** → generates `reports/WOW_REPORT.md` as before

Anything else shows a short help. No network, no model loaded.

---

## Summary

| Backend   | Internet? | Your hardware runs model? | Cost        |
|----------|-----------|---------------------------|-------------|
| **none** | No        | No                        | Free        |
| Ollama   | No        | Yes                       | Free, local |
| LM Studio| No        | Yes                       | Free, local |
| Groq     | Yes       | No                        | Free tier   |
| OpenAI   | Yes       | No                        | Paid        |

Use **LLM_BACKEND=none** to depend on neither the internet nor your hardware for the model.
