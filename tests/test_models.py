"""Tests for Event and Asset Pydantic models."""

import pytest
from pydantic import ValidationError

from src.models import Asset, Event


def test_event():
    # Valid construction
    event = Event(
        event_id="evt-001",
        name="Argentina vs France",
        home_team="Argentina",
        away_team="France",
        location="Lusail Stadium",
        start_date="2026-07-14T19:00:00Z",
        final_score="3-2",
        outcome_type="upset_victory",
        timeliness=0.87,
        ingested_at="2026-07-14T21:20:00Z",
    )
    assert event.event_id == "evt-001"
    assert event.outcome_type == "upset_victory"
    assert event.timeliness == 0.87

    # Null location is valid
    event_no_loc = Event(
        event_id="evt-002",
        name="Test Match",
        home_team="A",
        away_team="B",
        location=None,
        start_date="2026-07-14T19:00:00Z",
        final_score="1-0",
        outcome_type="expected_win",
        timeliness=0.5,
        ingested_at="2026-07-14T21:00:00Z",
    )
    assert event_no_loc.location is None

    # Invalid outcome_type rejected
    with pytest.raises(ValidationError):
        Event(
            event_id="evt-003",
            name="X",
            home_team="A",
            away_team="B",
            location=None,
            start_date="2026-07-14T19:00:00Z",
            final_score="1-0",
            outcome_type="blowout",
            timeliness=0.5,
            ingested_at="2026-07-14T21:00:00Z",
        )

    # timeliness below 0.0 rejected
    with pytest.raises(ValidationError):
        Event(
            event_id="evt-004",
            name="X",
            home_team="A",
            away_team="B",
            location=None,
            start_date="2026-07-14T19:00:00Z",
            final_score="1-0",
            outcome_type="draw",
            timeliness=-0.1,
            ingested_at="2026-07-14T21:00:00Z",
        )

    # timeliness above 1.0 rejected
    with pytest.raises(ValidationError):
        Event(
            event_id="evt-005",
            name="X",
            home_team="A",
            away_team="B",
            location=None,
            start_date="2026-07-14T19:00:00Z",
            final_score="1-0",
            outcome_type="draw",
            timeliness=1.1,
            ingested_at="2026-07-14T21:00:00Z",
        )


def test_asset():
    # Valid construction with all explicit fields
    asset = Asset(
        asset_id="ast-001",
        event_id="evt-001",
        content_url="/tmp/photo.jpg",
        status="ingested",
        upload_date="2026-07-14T21:00:00Z",
    )
    assert asset.asset_id == "ast-001"
    assert asset.status == "ingested"

    # status defaults to "ingested"
    asset_default = Asset(
        asset_id="ast-002",
        event_id="evt-001",
        content_url="/tmp/photo2.jpg",
        upload_date="2026-07-14T21:00:00Z",
    )
    assert asset_default.status == "ingested"

    # Nullable fields default to None
    assert asset_default.product_route is None
    assert asset_default.queue_type is None
    assert asset_default.embedding is None
    assert asset_default.scores is None
    assert asset_default.campaign_id is None
