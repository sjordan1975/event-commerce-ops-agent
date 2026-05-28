"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from src.models import Asset, AssetScores, Event, EventNarrative, HistoricalBaseline, KeyFigure, Player, SimilarAsset, SimilarityResult, VisionScoringOutput


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
    assert asset_default.similar_assets is None

    # similar_assets accepts a list of strings
    asset_with_neighbors = Asset(
        asset_id="ast-003",
        event_id="evt-001",
        content_url="/tmp/photo3.jpg",
        upload_date="2026-07-14T21:00:00Z",
        similar_assets=["asset-1", "asset-2"],
    )
    assert asset_with_neighbors.similar_assets == ["asset-1", "asset-2"]

    # similar_assets rejects non-string list elements
    with pytest.raises(ValidationError):
        Asset(
            asset_id="ast-004",
            event_id="evt-001",
            content_url="/tmp/photo4.jpg",
            upload_date="2026-07-14T21:00:00Z",
            similar_assets=[123],
        )


def test_similar_asset():
    # Happy-path construction
    sa = SimilarAsset(
        asset_id="past-asset-1",
        event_id="evt-past-1",
        similarity=0.85,
        product_route="poster",
        scores={"quality_score": 0.9},
    )
    assert sa.asset_id == "past-asset-1"
    assert sa.similarity == 0.85
    assert sa.product_route == "poster"

    # product_route=None accepted
    sa_no_route = SimilarAsset(
        asset_id="past-asset-2",
        event_id="evt-past-1",
        similarity=0.7,
        product_route=None,
        scores=None,
    )
    assert sa_no_route.product_route is None
    assert sa_no_route.scores is None

    # similarity below 0.0 rejected
    with pytest.raises(ValidationError):
        SimilarAsset(
            asset_id="x", event_id="y", similarity=-0.1,
            product_route=None, scores=None,
        )

    # similarity above 1.0 rejected
    with pytest.raises(ValidationError):
        SimilarAsset(
            asset_id="x", event_id="y", similarity=1.1,
            product_route=None, scores=None,
        )

    # extra fields rejected
    with pytest.raises(ValidationError):
        SimilarAsset(
            asset_id="x", event_id="y", similarity=0.5,
            product_route=None, scores=None, bad_field="oops",
        )


def test_similarity_result():
    sa = SimilarAsset(
        asset_id="past-asset-1",
        event_id="evt-past-1",
        similarity=0.85,
        product_route="poster",
        scores=None,
    )

    # Happy-path with neighbors
    sr = SimilarityResult(
        asset_id="current-asset-1",
        neighbors=[sa],
        inferred_route="poster",
    )
    assert sr.asset_id == "current-asset-1"
    assert len(sr.neighbors) == 1
    assert sr.inferred_route == "poster"

    # Empty neighbors accepted
    sr_empty = SimilarityResult(
        asset_id="current-asset-2",
        neighbors=[],
        inferred_route=None,
    )
    assert sr_empty.neighbors == []
    assert sr_empty.inferred_route is None

    # inferred_route="poster" accepted
    sr_routed = SimilarityResult(
        asset_id="current-asset-3",
        neighbors=[],
        inferred_route="poster",
    )
    assert sr_routed.inferred_route == "poster"


def test_asset_scores():
    # Happy-path construction
    scores = AssetScores(
        quality_score=0.9,
        merch_score=0.8,
        emotional_score=0.7,
        social_score=0.6,
        identity_score=0.5,
    )
    assert scores.quality_score == 0.9
    assert scores.identity_score == 0.5

    # Boundary values accepted
    AssetScores(quality_score=0.0, merch_score=0.0, emotional_score=0.0, social_score=0.0, identity_score=0.0)
    AssetScores(quality_score=1.0, merch_score=1.0, emotional_score=1.0, social_score=1.0, identity_score=1.0)

    # quality_score below 0.0 rejected
    with pytest.raises(ValidationError):
        AssetScores(quality_score=-0.1, merch_score=0.5, emotional_score=0.5, social_score=0.5, identity_score=0.5)

    # quality_score above 1.0 rejected
    with pytest.raises(ValidationError):
        AssetScores(quality_score=1.1, merch_score=0.5, emotional_score=0.5, social_score=0.5, identity_score=0.5)

    # identity_score out of range rejected
    with pytest.raises(ValidationError):
        AssetScores(quality_score=0.5, merch_score=0.5, emotional_score=0.5, social_score=0.5, identity_score=-0.5)

    # Missing dimension raises
    with pytest.raises(ValidationError):
        AssetScores(quality_score=0.5, merch_score=0.5, emotional_score=0.5, social_score=0.5)

    # Extra dimension raises (extra="forbid")
    with pytest.raises(ValidationError):
        AssetScores(
            quality_score=0.5,
            merch_score=0.5,
            emotional_score=0.5,
            social_score=0.5,
            identity_score=0.5,
            timeliness_score=0.5,
        )


def test_vision_scoring_output():
    scores = AssetScores(
        quality_score=0.7, merch_score=0.6, emotional_score=0.8,
        social_score=0.9, identity_score=0.7,
    )

    # Happy-path construction
    vso = VisionScoringOutput(scores=scores, detected_subjects=["Lionel Messi"])
    assert vso.scores.quality_score == 0.7
    assert vso.detected_subjects == ["Lionel Messi"]

    # Empty detected_subjects accepted
    vso_empty = VisionScoringOutput(scores=scores, detected_subjects=[])
    assert vso_empty.detected_subjects == []

    # Nested AssetScores validation propagates (out-of-range score raises)
    with pytest.raises(ValidationError):
        VisionScoringOutput(
            scores={
                "quality_score": 1.5,
                "merch_score": 0.5,
                "emotional_score": 0.5,
                "social_score": 0.5,
                "identity_score": 0.5,
            },
            detected_subjects=[],
        )


def test_asset_scores_retype_and_detected_subjects():
    # Construct with scores=None, detected_subjects=None (both default)
    a = Asset(
        asset_id="ast-001",
        event_id="evt-001",
        content_url="/tmp/photo.jpg",
        upload_date="2026-07-14T21:00:00Z",
    )
    assert a.scores is None
    assert a.detected_subjects is None

    # Construct with scores=AssetScores(...) and detected_subjects=list
    typed_scores = AssetScores(
        quality_score=0.9, merch_score=0.8, emotional_score=0.7,
        social_score=0.6, identity_score=0.9,
    )
    a2 = Asset(
        asset_id="ast-002",
        event_id="evt-001",
        content_url="/tmp/photo2.jpg",
        upload_date="2026-07-14T21:00:00Z",
        scores=typed_scores,
        detected_subjects=["Lionel Messi"],
    )
    assert a2.scores.quality_score == 0.9
    assert a2.detected_subjects == ["Lionel Messi"]

    # Dict scores no longer accepted (typed boundary rejects raw dict)
    with pytest.raises(ValidationError):
        Asset(
            asset_id="ast-003",
            event_id="evt-001",
            content_url="/tmp/photo3.jpg",
            upload_date="2026-07-14T21:00:00Z",
            scores={"quality_score": 0.9},
        )

    # detected_subjects=[123] rejected (list[str] enforced)
    with pytest.raises(ValidationError):
        Asset(
            asset_id="ast-004",
            event_id="evt-001",
            content_url="/tmp/photo4.jpg",
            upload_date="2026-07-14T21:00:00Z",
            detected_subjects=[123],
        )
