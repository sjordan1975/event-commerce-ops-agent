"""Shared eval helpers reused across all capability trace evals.

Mock strategy: patch src.db.events.get_client, src.db.assets.get_client,
src.db.performance.get_client, and src.db.player_context.get_client (the bound
names in each wrapper module) rather than src.db.get_client, since the wrappers
bind the name at import time via `from src.db import get_client`.
"""

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Union
from unittest.mock import patch

from src.agent import APP_NAME, build_coordinator, build_runner
from tests.conftest import build_embedding_fixture


def _make_mcp_envelope(docs: list[dict]) -> dict:
    """Encode a list of docs as a real MongoDB MCP find/aggregate envelope."""
    if not docs:
        return {"content": [{"type": "text", "text": "Query resulted in 0 documents."}]}
    uid = "mock-uuid-eval"
    data_text = (
        f"Query resulted in {len(docs)} documents.\n\n"
        f"<untrusted-user-data-{uid}>\n"
        f"{json.dumps(docs)}\n"
        f"</untrusted-user-data-{uid}>\n"
        f"Use the information above to respond."
    )
    return {
        "content": [
            {"type": "text", "text": f"Query resulted in {len(docs)} documents."},
            {"type": "text", "text": data_text},
        ]
    }


class _MockMCPClient:
    """Records all (tool_name, args) invocations; dispatches reads from a table.

    Dispatch table keyed by (tool_name, collection). Values are either a static
    list/dict or a callable(args) -> list/dict for cases that need to inspect
    the filter (e.g., two different find calls on the same collection).

    For aggregate calls whose pipeline starts with $vectorSearch, dispatch is
    keyed by (tool_name, collection, "$vectorSearch") — checked before the
    plain collection-keyed fallback. Register via register_vector_search().

    Write operations (insert-many, update-many) that have no handler registered
    return {"content": [{"type": "text", "text": "ok"}]} (response not parsed
    by any wrapper).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._handlers: dict[tuple, Union[list, dict, Callable]] = {}

    def register(
        self,
        tool_name: str,
        collection: str,
        handler: Union[list, dict, Callable],
    ) -> None:
        """Register a static result or callable handler for (tool_name, collection)."""
        self._handlers[(tool_name, collection)] = handler

    def register_vector_search(
        self,
        collection: str,
        results: list[dict],
    ) -> None:
        """Register a fixture for $vectorSearch aggregates on the given collection."""
        self._handlers[("aggregate", collection, "$vectorSearch")] = results

    async def call(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        collection = args.get("collection", "")

        # $vectorSearch dispatch: check pipeline[0] before falling back to collection key
        if tool_name == "aggregate":
            pipeline = args.get("pipeline", [])
            if pipeline and "$vectorSearch" in pipeline[0]:
                vs_key = ("aggregate", collection, "$vectorSearch")
                if vs_key in self._handlers:
                    handler = self._handlers[vs_key]
                    result = handler(args) if callable(handler) else handler
                    return _make_mcp_envelope(result)

        key = (tool_name, collection)
        if key in self._handlers:
            handler = self._handlers[key]
            result = handler(args) if callable(handler) else handler
            return _make_mcp_envelope(result)
        return {"content": [{"type": "text", "text": "ok"}]}


@contextmanager
def build_runner_with_mock_db():
    """Context manager that yields (runner, mock_client) with MongoDB patched out.

    Patches all four db module get_client bindings and patches
    src.capabilities.similarity._compute_image_embedding to return a
    deterministic 3072-dim fixture — no live Gemini calls during trace evals.
    """
    mock_client = _MockMCPClient()
    with (
        patch("src.db.events.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch("src.db.player_context.get_client", return_value=mock_client),
        patch(
            "src.capabilities.similarity._compute_image_embedding",
            return_value=build_embedding_fixture(),
        ),
    ):
        agent = build_coordinator()
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
