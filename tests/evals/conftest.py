"""Shared eval helpers reused across all capability trace evals.

Mock strategy: patch src.db.events.get_client and src.db.assets.get_client
(the bound names in each wrapper module) rather than src.db.get_client,
since the wrappers bind the name at import time via `from src.db import get_client`.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src.agent import APP_NAME, build_agent, build_runner


class _MockMCPClient:
    """Records all (tool_name, args) invocations made through it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        return {"content": [{"type": "text", "text": "ok"}]}


@contextmanager
def build_runner_with_mock_db():
    """Context manager that yields (runner, mock_client) with MongoDB patched out.

    Patches both src.db.events.get_client and src.db.assets.get_client so that
    no real MongoDB connection is attempted. The mock_client.calls list records
    every (tool_name, args) pair that would have gone to MongoDB.
    """
    mock_client = _MockMCPClient()
    with (
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        agent = build_agent()
        runner = build_runner(agent)
        yield runner, mock_client


def classify_part(part) -> dict:
    """Return a dict describing what kind of content this ADK part carries.

    Mirrors the pattern from spike/adk_event_capture.py (D-020 mechanism).
    """
    text = getattr(part, "text", None)
    if text:
        return {"kind": "text", "text": text}

    fc = getattr(part, "function_call", None)
    if fc is not None:
        return {
            "kind": "tool_call",
            "name": getattr(fc, "name", None),
            "args": dict(fc.args) if getattr(fc, "args", None) else {},
        }

    fr = getattr(part, "function_response", None)
    if fr is not None:
        return {
            "kind": "tool_response",
            "name": getattr(fr, "name", None),
            "response": dict(fr.response) if getattr(fr, "response", None) else {},
        }

    return {"kind": "unknown", "repr": repr(part)}


def _collect_parts(events: list) -> list[dict]:
    parts = []
    for event in events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            classified = classify_part(part)
            classified["author"] = event.author
            classified["is_final"] = event.is_final_response()
            parts.append(classified)
    return parts


def extract_tool_calls(events: list) -> list[dict]:
    """Return all tool_call parts from the event stream."""
    return [p for p in _collect_parts(events) if p["kind"] == "tool_call"]


def extract_tool_responses(events: list) -> list[dict]:
    """Return all tool_response parts from the event stream."""
    return [p for p in _collect_parts(events) if p["kind"] == "tool_response"]


def dump_trace(events: list, label: str) -> str:
    """Serialize event stream to tests/evals/_failures/{label}.json; return path."""
    failures_dir = Path(__file__).parent / "_failures"
    failures_dir.mkdir(exist_ok=True)
    path = failures_dir / f"{label}.json"
    path.write_text(
        json.dumps(_collect_parts(events), indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)
