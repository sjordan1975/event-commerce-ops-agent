"""Shared test fixtures and builder helpers reused across all test files."""

from datetime import datetime, timezone


def build_valid_event(**overrides) -> dict:
    """Return a minimal valid event document dict (Step 1 replaces with Pydantic model)."""
    base = {
        "event_id": "test-event-001",
        "name": "Argentina vs France",
        "home_team": "Argentina",
        "away_team": "France",
        "location": "Lusail Stadium",
        "start_date": "2026-06-01T19:00:00Z",
        "final_score": "3-2",
        "outcome_type": "upset_victory",
        "timeliness": 0.95,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def build_valid_asset(**overrides) -> dict:
    """Return a minimal valid asset document dict (Step 1 replaces with Pydantic model)."""
    base = {
        "asset_id": "test-asset-001",
        "event_id": "test-event-001",
        "content_url": "/tmp/test-photo.jpg",
        "status": "ingested",
        "product_route": None,
        "queue_type": None,
        "embedding": None,
        "scores": None,
        "campaign_id": None,
        "upload_date": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base
