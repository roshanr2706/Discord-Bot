"""Read/write the rolling chat-memory snapshot used for summary context."""

import json
import os
from datetime import datetime, timezone

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
MEMORY_PATH = os.path.join(CONFIG_DIR, "chat_memory.json")

EMPTY = {"updated_at": None, "summary": None}


def load_memory() -> dict:
    """Return the memory dict, or an empty stub if nothing has been saved yet."""
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(EMPTY)


def save_memory(summary: str) -> dict:
    """Persist a new summary snapshot stamped with the current UTC time."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    }
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def get_context_block() -> str | None:
    """Format the stored memory for prompt injection, or None if empty."""
    data = load_memory()
    if not data.get("summary"):
        return None
    return (
        f"[CHAT CONTEXT — last updated {data['updated_at']}]\n"
        f"{data['summary']}\n"
        f"[END CONTEXT]\n"
    )
