"""Prompt loading.

Prompts live in versioned markdown files rather than Python string literals so a
prompt change is a reviewable diff, and so the version used by a run can be
recorded alongside its result.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
PROMPT_VERSION = "v1"


@lru_cache
def load_prompt(name: str, version: str = PROMPT_VERSION) -> str:
    path = PROMPT_DIR / f"{name}_{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt not found: {path.name}")
    return path.read_text(encoding="utf-8").strip()
