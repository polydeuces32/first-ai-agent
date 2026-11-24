from __future__ import annotations

import os

import httpx


LLAMA_BASE_URL = os.getenv("LLAMA_BASE_URL", "http://127.0.0.1:9931")


def generate_answer(question: str, evidence: str) -> str:
    prompt = (
        "Answer the question using only the provided evidence. "
        "If the evidence does not support an answer, say so.\n\n"
        f"EVIDENCE:\n{evidence}\n\n"
        f"QUESTION:\n{question}"
    )

    response = httpx.post(
        f"{LLAMA_BASE_URL}/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 512,
        },
        timeout=120.0,
    )
    response.raise_for_status()

    return response.json()["choices"][0]["message"]["content"].strip()
