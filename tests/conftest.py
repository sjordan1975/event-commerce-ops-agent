"""Shared test fixtures and builder helpers reused across all test files."""

from datetime import datetime, timezone

from src.models import Asset, Event


def build_valid_event(**overrides) -> Event:
    """Return a minimal valid Event instance with sensible defaults."""
    base = {
        "event_id": "test-event-001",
        "name": "Argentina vs France",
        "home_team": "Argentina",
        "away_team": "France",
        "location": "Lusail Stadium",
        "start_date": "2026-06-01T19:00:00Z",
        "final_score": "3-2",
        "outcome_type": "upset_victory",
        "timeliness": 0.87,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return Event(**base)


def build_valid_asset(**overrides) -> Asset:
    """Return a minimal valid Asset instance with sensible defaults."""
    base = {
        "asset_id": "test-asset-001",
        "event_id": "test-event-001",
        "content_url": "/tmp/test-photo.jpg",
        "status": "ingested",
        "upload_date": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return Asset(**base)
