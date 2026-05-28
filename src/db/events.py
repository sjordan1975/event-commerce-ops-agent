"""Internal MongoDB wrapper for the events collection."""

from src.db import _parse_docs_response, get_client
from src.models import Event, EventNarrative


async def record_event(event: Event) -> str:
    """Internal: records an event in the events collection. Called by the
    `ingest_event_batch` capability; not agent-facing. Returns the event_id."""
    await get_client().call("insert-many", {
        "database": "event_commerce",
        "collection": "events",
        "documents": [event.model_dump(mode="json")],
    })
    return event.event_id


async def get_event(event_id: str) -> Event | None:
    """Return the Event document for event_id, or None if not found."""
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "events",
        "filter": {"event_id": event_id},
    })
    docs = _parse_docs_response(envelope)
    if not docs:
        return None
    return Event.model_validate(docs[0])


async def find_past_events_by_outcome(
    outcome_type: str, exclude_event_id: str
) -> list[Event]:
    """Return events matching outcome_type, excluding the given event_id."""
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "events",
        "filter": {
            "outcome_type": outcome_type,
            "event_id": {"$ne": exclude_event_id},
        },
    })
    docs = _parse_docs_response(envelope)
    return [Event.model_validate(d) for d in docs]


async def update_event_narrative(event_id: str, narrative: EventNarrative) -> None:
    """Persist the EventNarrative onto the events document (per D-022)."""
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "events",
        "filter": {"event_id": event_id},
        "update": {"$set": {"event_narrative": narrative.model_dump(mode="json")}},
    })
