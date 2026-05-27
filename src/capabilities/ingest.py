"""ingest_event_batch — agent-facing capability for Step 1."""

import uuid
from datetime import datetime, timezone

from src.db.assets import record_assets
from src.db.events import record_event
from src.errors import PreconditionError
from src.models import Asset, Event
from src.timeliness import BASE_SCORES, compute_timeliness

_REQUIRED_FIELDS = ["name", "home_team", "away_team", "final_score", "start_date", "outcome_type"]

_FIELD_REMEDIATION = {
    "name": "provide the match name (e.g. 'Argentina vs France')",
    "home_team": "provide the home team name",
    "away_team": "provide the away team name",
    "final_score": "provide the final score (e.g. '3-2')",
    "start_date": "provide the match start time as ISO 8601 UTC (e.g. '2026-07-14T19:00:00Z')",
    "outcome_type": f"provide one of: {', '.join(BASE_SCORES)}",
}


async def ingest_event_batch(images: list[str], event_metadata: dict) -> dict:
    """Ingests an event and its associated images.

    Records the event with computed timeliness and bulk-inserts all images
    with status='ingested'. Returns {"event_id": str, "asset_ids": list[str]}.

    Required fields in event_metadata:
        - name, final_score (strings)
        - home_team: team listed first in fixture notation (e.g. "X vs Y" → X is home)
        - away_team: team listed second in fixture notation
        - start_date (ISO 8601 UTC string, e.g. "2026-07-14T19:00:00Z")
        - outcome_type: categorize the result —
            upset_victory  → underdog/lower-ranked team won
            extra_time_win → match went to extra time or penalties before a winner
            expected_win   → favored/higher-ranked team won as expected
            draw           → match ended level after full time
    Optional:
        - location (string)

    Raises PreconditionError if required fields are missing or outcome_type is invalid;
    the error message identifies the missing/invalid field for self-correction.

    Typically the first capability called for a new event batch — call before
    build_event_context, find_similar_assets, or score_assets_with_vision.
    """
    missing: dict[str, str] = {}

    for field in _REQUIRED_FIELDS:
        if not event_metadata.get(field):
            missing[field] = _FIELD_REMEDIATION[field]

    if not missing and event_metadata.get("outcome_type") not in BASE_SCORES:
        missing["outcome_type"] = _FIELD_REMEDIATION["outcome_type"]

    if missing:
        raise PreconditionError(
            capability="ingest_event_batch",
            context="event_metadata",
            missing=missing,
        )

    event_id = str(uuid.uuid4())
    timeliness_result = compute_timeliness(
        event_metadata["outcome_type"], event_metadata["start_date"]
    )

    event = Event(
        event_id=event_id,
        name=event_metadata["name"],
        home_team=event_metadata["home_team"],
        away_team=event_metadata["away_team"],
        location=event_metadata.get("location"),
        start_date=event_metadata["start_date"],
        final_score=event_metadata["final_score"],
        outcome_type=event_metadata["outcome_type"],
        timeliness=timeliness_result["timeliness"],
        ingested_at=datetime.now(timezone.utc).isoformat(),
    )

    confirmed_event_id = await record_event(event)

    now = datetime.now(timezone.utc).isoformat()
    assets = [
        Asset(
            asset_id=str(uuid.uuid4()),
            event_id=event_id,
            content_url=img,
            status="ingested",
            upload_date=now,
        )
        for img in images
    ]

    asset_ids = await record_assets(event_id, assets)

    return {"event_id": confirmed_event_id, "asset_ids": asset_ids}
