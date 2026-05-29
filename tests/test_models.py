"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from src.models import Approval, Asset, AssetScores, Campaign, Event, EventNarrative, GeneratedCopy, HistoricalBaseline, KeyFigure, Player, QueueItem, ReviewQueue, SimilarAsset, SimilarityResult, VisionScoringOutput


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

    # queue_rank and queue_rationale default to None
    assert asset_default.queue_rank is None
    assert asset_default.queue_rationale is None

    # queue_rank and queue_rationale accept explicit values
    asset_queued = Asset(
        asset_id="ast-005",
        event_id="evt-001",
        content_url="/tmp/photo5.jpg",
        upload_date="2026-07-14T21:00:00Z",
        queue_rank=1,
        queue_rationale="Features the event's key figure",
    )
    assert asset_queued.queue_rank == 1
    assert asset_queued.queue_rationale == "Features the event's key figure"

    # queue_rank="first" rejected (must be int)
    with pytest.raises(ValidationError):
        Asset(
            asset_id="ast-006",
            event_id="evt-001",
            content_url="/tmp/photo6.jpg",
            upload_date="2026-07-14T21:00:00Z",
            queue_rank="first",
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


def test_queue_item():
    # Happy-path construction
    item = QueueItem(
        asset_id="a1",
        queue_type="exploitation",
        rank=1,
        product_route="poster",
        rationale="Features the event's key figure",
    )
    assert item.asset_id == "a1"
    assert item.queue_type == "exploitation"
    assert item.rank == 1
    assert item.product_route == "poster"

    # product_route=None is valid
    item_no_route = QueueItem(
        asset_id="a2",
        queue_type="discovery",
        rank=1,
        product_route=None,
        rationale="Worth surfacing despite no match",
    )
    assert item_no_route.product_route is None

    # Invalid queue_type rejected
    with pytest.raises(ValidationError):
        QueueItem(
            asset_id="a3",
            queue_type="exploration",
            rank=1,
            product_route="poster",
            rationale="test",
        )

    # Invalid product_route rejected
    with pytest.raises(ValidationError):
        QueueItem(
            asset_id="a4",
            queue_type="exploitation",
            rank=1,
            product_route="mug",
            rationale="test",
        )

    # Round-trips through model_validate_json
    json_str = item.model_dump_json()
    restored = QueueItem.model_validate_json(json_str)
    assert restored.asset_id == item.asset_id

    # model_validate on dict works (output_key lands a dict)
    d = item.model_dump(mode="json")
    restored_dict = QueueItem.model_validate(d)
    assert restored_dict.rank == 1


def test_review_queue():
    item_expl = QueueItem(
        asset_id="a1", queue_type="exploitation", rank=1,
        product_route="poster", rationale="Messi in frame",
    )
    item_disc = QueueItem(
        asset_id="a3", queue_type="discovery", rank=1,
        product_route="social_only", rationale="Emotional shot worth surfacing",
    )

    # Happy-path construction
    rq = ReviewQueue(
        event_id="evt-demo-1",
        exploitation=[item_expl],
        discovery=[item_disc],
        strategy_summary="Rich exploitation, one pointed discovery",
    )
    assert rq.event_id == "evt-demo-1"
    assert len(rq.exploitation) == 1
    assert len(rq.discovery) == 1
    assert rq.strategy_summary != ""

    # Empty lists are valid
    rq_empty = ReviewQueue(
        event_id="evt-demo-2",
        exploitation=[],
        discovery=[],
        strategy_summary="No candidates",
    )
    assert rq_empty.exploitation == []
    assert rq_empty.discovery == []

    # Round-trips through model_validate_json
    json_str = rq.model_dump_json()
    restored = ReviewQueue.model_validate_json(json_str)
    assert restored.event_id == "evt-demo-1"
    assert restored.exploitation[0].queue_type == "exploitation"

    # model_validate on dict works
    d = rq.model_dump(mode="json")
    restored_dict = ReviewQueue.model_validate(d)
    assert restored_dict.discovery[0].product_route == "social_only"

    # Invalid queue_type in nested item propagates
    with pytest.raises(ValidationError):
        ReviewQueue(
            event_id="evt-demo-3",
            exploitation=[{
                "asset_id": "a1",
                "queue_type": "invalid_type",
                "rank": 1,
                "product_route": "poster",
                "rationale": "test",
            }],
            discovery=[],
            strategy_summary="test",
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


def test_generated_copy():
    # Happy-path construction
    gc = GeneratedCopy(
        headline="Messi caps Argentina's extra-time upset",
        caption="The night Argentina ended France's reign — limited edition print.",
        hashtags=["#WorldCup2026", "#ArgentinaVsFrance"],
    )
    assert gc.headline == "Messi caps Argentina's extra-time upset"
    assert len(gc.hashtags) == 2

    # Empty hashtags list is valid
    gc_no_tags = GeneratedCopy(
        headline="A win for the ages",
        caption="Historic match.",
        hashtags=[],
    )
    assert gc_no_tags.hashtags == []

    # Round-trips through model_validate_json (the response_schema path)
    json_str = gc.model_dump_json()
    restored = GeneratedCopy.model_validate_json(json_str)
    assert restored.headline == gc.headline
    assert restored.hashtags == gc.hashtags

    # Missing headline rejected (required field)
    with pytest.raises(ValidationError):
        GeneratedCopy(caption="A caption.", hashtags=[])

    # No extra="forbid" — extra fields silently tolerated (Gemini response_schema compat)
    gc_extra = GeneratedCopy(
        headline="headline",
        caption="caption",
        hashtags=[],
        extra_field="ignored",
    )
    assert gc_extra.headline == "headline"


def test_campaign():
    gc = GeneratedCopy(
        headline="Messi caps Argentina's extra-time upset",
        caption="Limited edition print.",
        hashtags=["#WorldCup2026"],
    )

    # Happy-path construction
    camp = Campaign(
        campaign_id="cmp-1",
        asset_id="a1",
        event_id="evt-demo-1",
        product_type="poster",
        generated_copy=gc,
        platform_target="shopify",
        timing_recommendation="2026-07-14T22:00:00Z",
        created_at="2026-07-14T21:00:00Z",
    )
    assert camp.campaign_id == "cmp-1"
    assert camp.status == "draft"
    assert camp.execution is None

    # product_type=None accepted (social_only route)
    camp_social = Campaign(
        campaign_id="cmp-2",
        asset_id="a2",
        event_id="evt-demo-1",
        product_type=None,
        generated_copy=gc,
        platform_target="social",
        timing_recommendation="2026-07-14T22:00:00Z",
        created_at="2026-07-14T21:00:00Z",
    )
    assert camp_social.product_type is None

    # platform_target rejects value outside the three literals
    with pytest.raises(ValidationError):
        Campaign(
            campaign_id="cmp-3",
            asset_id="a3",
            event_id="evt-demo-1",
            product_type=None,
            generated_copy=gc,
            platform_target="instagram",
            timing_recommendation="2026-07-14T22:00:00Z",
            created_at="2026-07-14T21:00:00Z",
        )

    # product_type rejects value outside poster/tshirt/None
    with pytest.raises(ValidationError):
        Campaign(
            campaign_id="cmp-4",
            asset_id="a4",
            event_id="evt-demo-1",
            product_type="mug",
            generated_copy=gc,
            platform_target="shopify",
            timing_recommendation="2026-07-14T22:00:00Z",
            created_at="2026-07-14T21:00:00Z",
        )

    # extra="forbid" rejects unknown field
    with pytest.raises(ValidationError):
        Campaign(
            campaign_id="cmp-5",
            asset_id="a5",
            event_id="evt-demo-1",
            product_type="poster",
            generated_copy=gc,
            platform_target="shopify",
            timing_recommendation="2026-07-14T22:00:00Z",
            created_at="2026-07-14T21:00:00Z",
            unknown_field="oops",
        )


def test_approval():
    # Happy-path construction
    apr = Approval(
        approval_id="apr-1",
        campaign_id="cmp-1",
        asset_id="a1",
        created_at="2026-07-14T21:00:00Z",
    )
    assert apr.approval_id == "apr-1"
    assert apr.status == "pending"
    assert apr.reviewer_notes is None
    assert apr.decided_at is None

    # Explicit status, reviewer_notes, decided_at accepted
    apr_full = Approval(
        approval_id="apr-2",
        campaign_id="cmp-1",
        asset_id="a1",
        status="approved",
        reviewer_notes="Looks good",
        created_at="2026-07-14T21:00:00Z",
        decided_at="2026-07-14T22:00:00Z",
    )
    assert apr_full.status == "approved"
    assert apr_full.reviewer_notes == "Looks good"
    assert apr_full.decided_at == "2026-07-14T22:00:00Z"

    # extra="forbid" rejects unknown field
    with pytest.raises(ValidationError):
        Approval(
            approval_id="apr-3",
            campaign_id="cmp-1",
            asset_id="a1",
            created_at="2026-07-14T21:00:00Z",
            bad_field="oops",
        )
