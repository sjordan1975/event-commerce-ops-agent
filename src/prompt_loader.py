"""Loads versioned prompt files from the prompts/ directory."""

import os
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt file by name from the active prompt version directory."""
    version = os.environ.get("PROMPT_VERSION", "v2")
    path = _PROMPTS_DIR / version / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt '{name}' not found at {path} (PROMPT_VERSION={version})"
        )
    return path.read_text(encoding="utf-8")
