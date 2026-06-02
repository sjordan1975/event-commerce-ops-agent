"""In-memory registry for Gemini-generated preview mockup image bytes.

Writer: src/capabilities/execution.py (generates and stores bytes).
Reader: src/api/server.py (serves via GET /api/mockup/{asset_id}).
No circular import — neither direction needs the other's module.
"""

_store: dict[str, bytes] = {}


def store_mockup(asset_id: str, data: bytes) -> None:
    """Store generated mockup bytes keyed by asset_id."""
    _store[asset_id] = data


def get_mockup(asset_id: str) -> "bytes | None":
    """Return stored bytes, or None if not yet generated."""
    return _store.get(asset_id)
