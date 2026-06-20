"""Thin async wrapper that routes generation to Anthropic or Ollama.

Backend is chosen with the AI_BACKEND env var ("anthropic" or "ollama").
"""

import os

import httpx

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"


def _backend() -> str:
    return os.getenv("AI_BACKEND", "anthropic").strip().lower()


def _summarize_prompt(text: str) -> str:
    return (
        "Summarize the following chat transcript. Capture the main topics, "
        "any decisions or conclusions, and notable back-and-forth. Be concise "
        "and write in plain prose or short bullets.\n\n"
        f"Transcript:\n{text}"
    )


async def _anthropic(prompt: str, max_tokens: int) -> str:
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


async def _ollama(prompt: str, max_tokens: int) -> str:
    host = os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


async def _generate(prompt: str, max_tokens: int) -> str:
    backend = _backend()
    if backend == "anthropic":
        return await _anthropic(prompt, max_tokens)
    if backend == "ollama":
        return await _ollama(prompt, max_tokens)
    raise RuntimeError(f"unknown AI_BACKEND: {backend!r} (use 'anthropic' or 'ollama')")


async def summarize(text: str, max_tokens: int = 500) -> str:
    return await _generate(_summarize_prompt(text), max_tokens)
