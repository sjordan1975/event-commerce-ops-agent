"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from src.models import Asset, Event, EventNarrative, HistoricalBaseline, KeyFigure, Player


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

    # event_narrative defaults to None
    assert event.event_narrative is None

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

    # event_narrative accepts a valid EventNarrative
    narrative = EventNarrative(
        event_id="evt-001",
        narrative_angle="Argentina upsets France in dramatic final",
        key_figures=[],
        commercial_timing="Aggressive — 4h window remaining",
        historical_baseline=HistoricalBaseline(
            outcome_type="upset_victory",
            past_event_count=2,
            top_product_route="poster",
            total_orders=500,
            total_impressions=20000,
            notes="2 past upsets; poster routes dominated",
        ),
    )
    event_with_narrative = Event(
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
        event_narrative=narrative,
    )
    assert event_with_narrative.event_narrative is not None
    assert event_with_narrative.event_narrative.event_id == "evt-001"

    # Malformed event_narrative dict rejected by Pydantic
    with pytest.raises(ValidationError):
        Event(
            event_id="evt-006",
            name="X",
            home_team="A",
            away_team="B",
            location=None,
            start_date="2026-07-14T19:00:00Z",
            final_score="1-0",
            outcome_type="draw",
            timeliness=0.5,
            ingested_at="2026-07-14T21:00:00Z",
            event_narrative={"bad_field": "missing all required fields"},
        )

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


def test_player():
    # Valid construction
    player = Player(
        player_id="uuid-001",
        name="Lionel Messi",
        nationality="Argentina",
        team="Argentina",
        position="Forward",
        notable_facts=["5th World Cup appearance", "2022 World Cup winner"],
        career_milestones="Widely regarded as final World Cup; 2022 champion",
        commercial_signal="high",
    )
    assert player.player_id == "uuid-001"
    assert player.name == "Lionel Messi"
    assert player.notable_facts == ["5th World Cup appearance", "2022 World Cup winner"]
    assert player.commercial_signal == "high"

    # Empty notable_facts is valid (list[str] with 0 items)
    player_empty = Player(
        player_id="uuid-002",
        name="Test Player",
        nationality="France",
        team="France",
        position="Midfielder",
        notable_facts=[],
        career_milestones="N/A",
        commercial_signal="low",
    )
    assert player_empty.notable_facts == []

    # Invalid commercial_signal rejected
    with pytest.raises(ValidationError):
        Player(
            player_id="uuid-003",
            name="X",
            nationality="Y",
            team="Z",
            position="Goalkeeper",
            notable_facts=[],
            career_milestones="N/A",
            commercial_signal="very_high",
        )

    # Extra fields rejected
    with pytest.raises(ValidationError):
        Player(
            player_id="uuid-004",
            name="X",
            nationality="Y",
            team="Z",
            position="Defender",
            notable_facts=[],
            career_milestones="N/A",
            commercial_signal="medium",
            extra_field="oops",
        )


def test_key_figure():
    kf = KeyFigure(
        name="Lionel Messi",
        team="Argentina",
        relevance="Scored the winning penalty",
        grounded_facts=["2022 World Cup winner"],
        commercial_signal="high",
    )
    assert kf.name == "Lionel Messi"
    assert kf.grounded_facts == ["2022 World Cup winner"]
    assert kf.commercial_signal == "high"

    # Empty grounded_facts is valid
    kf_empty = KeyFigure(
        name="X",
        team="Y",
        relevance="Z",
        grounded_facts=[],
        commercial_signal="low",
    )
    assert kf_empty.grounded_facts == []

    # Invalid commercial_signal rejected
    with pytest.raises(ValidationError):
        KeyFigure(
            name="X",
            team="Y",
            relevance="Z",
            grounded_facts=[],
            commercial_signal="ultra",
        )


def test_historical_baseline():
    baseline = HistoricalBaseline(
        outcome_type="upset_victory",
        past_event_count=3,
        top_product_route="poster",
        total_orders=300,
        total_impressions=15000,
        notes="3 past upsets; poster was the top route",
    )
    assert baseline.past_event_count == 3
    assert baseline.top_product_route == "poster"

    # top_product_route=None is valid (no cohort data)
    baseline_empty = HistoricalBaseline(
        outcome_type="upset_victory",
        past_event_count=0,
        top_product_route=None,
        total_orders=0,
        total_impressions=0,
        notes="no historical data yet",
    )
    assert baseline_empty.top_product_route is None


def test_event_narrative():
    baseline = HistoricalBaseline(
        outcome_type="upset_victory",
        past_event_count=2,
        top_product_route="poster",
        total_orders=200,
        total_impressions=10000,
        notes="2 past upsets",
    )
    kf = KeyFigure(
        name="Lionel Messi",
        team="Argentina",
        relevance="Tournament top scorer",
        grounded_facts=["2022 World Cup winner"],
        commercial_signal="high",
    )
    narrative = EventNarrative(
        event_id="evt-001",
        narrative_angle="Messi crowns legendary career with World Cup title",
        key_figures=[kf],
        commercial_timing="Aggressive — timeliness 0.95, ~4h window remaining",
        historical_baseline=baseline,
    )
    assert narrative.event_id == "evt-001"
    assert len(narrative.key_figures) == 1
    assert narrative.historical_baseline.outcome_type == "upset_victory"

    # Empty key_figures is valid
    narrative_no_figures = EventNarrative(
        event_id="evt-002",
        narrative_angle="Upset victory with no seeded players",
        key_figures=[],
        commercial_timing="Moderate",
        historical_baseline=baseline,
    )
    assert narrative_no_figures.key_figures == []

    # Invalid commercial_signal on nested KeyFigure rejected
    with pytest.raises(ValidationError):
        EventNarrative(
            event_id="evt-003",
            narrative_angle="Test",
            key_figures=[{
                "name": "X",
                "team": "Y",
                "relevance": "Z",
                "grounded_facts": [],
                "commercial_signal": "invalid",
            }],
            commercial_timing="Test",
            historical_baseline=baseline,
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
