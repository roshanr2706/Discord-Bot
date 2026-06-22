"""Thin async wrapper that routes generation to Anthropic or Ollama.

Backend is chosen with the AI_BACKEND env var ("anthropic" or "ollama").
"""

import os

import httpx

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"
# Local generation can be slow, especially the first call (cold model load).
# Override with OLLAMA_TIMEOUT (seconds) if your hardware needs longer.
DEFAULT_OLLAMA_TIMEOUT = 300.0


def _backend() -> str:
    return os.getenv("AI_BACKEND", "anthropic").strip().lower()


def _summarize_prompt(text: str, context: str | None) -> str:
    parts = []
    if context:
        parts.append(
            "Here is recent chat history for context. Use it to interpret "
            "references and ongoing topics, but do not summarize it directly:\n"
            f"{context}"
        )
    parts.append(
        "Summarize the following chat transcript. Capture the main topics, "
        "any decisions or conclusions, and notable back-and-forth. Be concise "
        "and write in plain prose or short bullets. Attribute points to people "
        "by the display names shown in the transcript (e.g. 'Alex said...'), "
        "not generic labels like 'a user' or 'one participant'.\n\n"
        f"Transcript:\n{text}"
    )
    return "\n\n".join(parts)


def _condense_prompt(text: str) -> str:
    return (
        "Condense the following chat transcript into a compact memory snapshot "
        "of a few bullet points. Cover the topics discussed, any decisions made, "
        "and anything useful for understanding future messages. Keep the display "
        "names of who said what (e.g. 'Alex is bringing snacks'), not generic "
        "labels like 'a user'. Keep it short.\n\n"
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
    read_timeout = float(os.getenv("OLLAMA_TIMEOUT", DEFAULT_OLLAMA_TIMEOUT))

    # Fail fast if the host is unreachable (connect), but allow a long read so
    # slow local generation doesn't get cut off.
    timeout = httpx.Timeout(read_timeout, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    # Ollama defaults to a tiny context window (~2048), which
                    # silently truncates long transcripts. Bump it so the whole
                    # prompt (instruction + chat) actually fits.
                    "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
                },
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


async def summarize(text: str, context: str | None = None, max_tokens: int | None = None) -> str:
    if max_tokens is None:
        max_tokens = int(os.getenv("AI_SUMMARY_MAX_TOKENS", "1000"))
    return await _generate(_summarize_prompt(text, context), max_tokens)


def _split_on_lines(text: str, budget: int) -> list[str]:
    """Split text into chunks of at most `budget` chars, breaking on newlines."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if current and len(current) + 1 + len(line) > budget:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


async def condense(text: str, max_tokens: int | None = None) -> str:
    if max_tokens is None:
        max_tokens = int(os.getenv("AI_MEMORY_MAX_TOKENS", "600"))

    # 3 hours of chat can exceed the model's context window. If the transcript
    # is too big, condense it in pieces and then condense those notes together
    # (map-reduce) so nothing gets silently truncated.
    budget = int(os.getenv("AI_INPUT_CHAR_BUDGET", "16000"))
    if len(text) <= budget:
        return await _generate(_condense_prompt(text), max_tokens)

    partials = []
    for chunk in _split_on_lines(text, budget):
        partials.append(await _generate(_condense_prompt(chunk), max_tokens))
    combined = "\n".join(partials)
    # Safety net: if even the combined notes are huge, trim before the final pass.
    if len(combined) > budget:
        combined = combined[:budget]
    return await _generate(_condense_prompt(combined), max_tokens)
