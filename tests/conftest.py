"""Shared test fixtures and builder helpers reused across all test files."""

from datetime import datetime, timezone

from src.models import Asset, AssetScores, Event, EventNarrative, HistoricalBaseline, KeyFigure, Player, QueueItem, ReviewQueue, SimilarAsset, VisionScoringOutput


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


def build_valid_player(**overrides) -> Player:
    """Return a valid Player instance with defaults matching the player_context JSON example."""
    base = {
        "player_id": "player-uuid-001",
        "name": "Lionel Messi",
        "nationality": "Argentina",
        "team": "Argentina",
        "position": "Forward",
        "notable_facts": [
            "5th World Cup appearance",
            "2022 World Cup winner",
            "All-time leading scorer in World Cup finals",
        ],
        "career_milestones": "Widely regarded as final World Cup; 2022 champion",
        "commercial_signal": "high",
    }
    base.update(overrides)
    return Player(**base)


def build_valid_similar_asset(**overrides) -> SimilarAsset:
    """Return a valid SimilarAsset instance with sensible defaults."""
    base = {
        "asset_id": "past-asset-1",
        "event_id": "evt-past-1",
        "similarity": 0.85,
        "product_route": "poster",
        "scores": {"quality_score": 0.9},
    }
    base.update(overrides)
    return SimilarAsset(**base)


def build_embedding_fixture() -> list[float]:
    """Return a deterministic 3072-element float list for tests (no live API)."""
    return [0.1] * 3072


def build_valid_asset_scores(**overrides) -> AssetScores:
    """Return a valid AssetScores instance with sensible defaults (all dims 0.7)."""
    base = {
        "quality_score": 0.7,
        "merch_score": 0.7,
        "emotional_score": 0.7,
        "social_score": 0.7,
        "identity_score": 0.7,
    }
    base.update(overrides)
    return AssetScores(**base)


def build_valid_vision_scoring_output(**overrides) -> VisionScoringOutput:
    """Return a valid VisionScoringOutput with default scores and detected_subjects."""
    base = {
        "scores": build_valid_asset_scores(),
        "detected_subjects": ["Lionel Messi"],
    }
    base.update(overrides)
    return VisionScoringOutput(**base)


def build_valid_queue_item(**overrides) -> QueueItem:
    """Return a valid QueueItem instance with sensible defaults."""
    base = {
        "asset_id": "a1",
        "queue_type": "exploitation",
        "rank": 1,
        "product_route": "poster",
        "rationale": "features the event's key figure",
    }
    base.update(overrides)
    return QueueItem(**base)


def build_valid_review_queue(**overrides) -> ReviewQueue:
    """Return a valid ReviewQueue instance with one exploitation and one discovery item."""
    base = {
        "event_id": "evt-demo-1",
        "exploitation": [build_valid_queue_item()],
        "discovery": [build_valid_queue_item(
            asset_id="a3",
            queue_type="discovery",
            product_route="social_only",
            rationale="no match but worth surfacing",
        )],
        "strategy_summary": "rich exploitation, one pointed discovery",
    }
    base.update(overrides)
    return ReviewQueue(**base)


def build_valid_event_narrative(**overrides) -> EventNarrative:
    """Return a valid EventNarrative instance with at least one KeyFigure and a populated HistoricalBaseline."""
    baseline = HistoricalBaseline(
        outcome_type="upset_victory",
        past_event_count=3,
        top_product_route="poster",
        total_orders=450,
        total_impressions=22000,
        notes="3 past upsets; poster routes dominated conversion",
    )
    kf = KeyFigure(
        name="Lionel Messi",
        team="Argentina",
        relevance="Scored the decisive penalty in the shootout",
        grounded_facts=["2022 World Cup winner", "5th World Cup appearance"],
        commercial_signal="high",
    )
    base = {
        "event_id": "test-event-001",
        "narrative_angle": "Messi crowns legendary career as Argentina defeats France on penalties",
        "key_figures": [kf],
        "commercial_timing": "Aggressive — timeliness 0.87, ~6h window remaining",
        "historical_baseline": baseline,
    }
    base.update(overrides)
    return EventNarrative(**base)
