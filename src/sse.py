"""Module-level SSE event queue registry.

Keyed by session_id (string). Queues are asyncio.Queue objects that live on the
server's event loop. Capability nodes and coordinator tools call get_queue() to
emit events; the FastAPI SSE generator drains the queue.

Intentionally has NO imports from src/api/ — dependency direction is
src/capabilities/ → src/sse, NOT src/capabilities/ → src/api/.
"""

import asyncio

_queues: dict[str, asyncio.Queue] = {}


def create_queue(session_id: str) -> asyncio.Queue:
    """Create and register a new queue for the given session."""
    q: asyncio.Queue = asyncio.Queue()
    _queues[session_id] = q
    return q


def get_queue(session_id: str) -> "asyncio.Queue | None":
    """Return the queue for session_id, or None if not found."""
    return _queues.get(session_id)


def close_queue(session_id: str) -> None:
    """Remove the queue from the registry (called after SSE stream closes)."""
    _queues.pop(session_id, None)
