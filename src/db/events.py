"""Internal MongoDB wrapper for the events collection."""

from src.db import get_client
from src.models import Event


async def record_event(event: Event) -> str:
    """Internal: records an event in the events collection. Called by the
    `ingest_event_batch` capability; not agent-facing. Returns the event_id."""
    await get_client().call("insert-many", {
        "database": "event_commerce",
        "collection": "events",
        "documents": [event.model_dump(mode="json")],
    })
    return event.event_id
