"""Smoke tests: verify _MockMCPClient dispatch correctly seeds all Step 2–6 wrapper calls.

Does NOT run the agent — exercises wrappers directly against the mock client to
confirm the envelope encoding matches what each wrapper's parse logic expects.
"""

import pytest

from tests.conftest import (
    build_valid_event,
    build_valid_event_narrative,
    build_valid_player,
    build_embedding_fixture,
    build_valid_similar_asset,
    build_valid_generated_copy,
)
from tests.evals.conftest import (
    _MockMCPClient,
    _CANNED_COPY,
    STEP6_QUEUED_IDS,
    STEP6_UNSURFACED_ID,
    STEP6_CROWD_ASSET_ID,
    _make_step6_assets_find_handler,
    patch_draft_copy_for_asset,
    build_runner_with_mock_db,
)


def _make_event_find_handler(seeded_event, past_events):
    """Callable dispatcher for ('find', 'events') — routes by filter shape."""
    seeded_doc = seeded_event.model_dump(mode="json")
    past_docs = [e.model_dump(mode="json") for e in past_events]

    def handler(args: dict) -> list:
        f = args.get("filter", {})
        event_id_filter = f.get("event_id")
        if isinstance(event_id_filter, str):
            return [d for d in [seeded_doc] if d["event_id"] == event_id_filter]
        elif isinstance(event_id_filter, dict) and "$ne" in event_id_filter:
            exclude = event_id_filter["$ne"]
            outcome = f.get("outcome_type")
            return [d for d in past_docs if d["event_id"] != exclude and (outcome is None or d["outcome_type"] == outcome)]
        return []

    return handler


@pytest.mark.anyio
async def test_mock_dispatch_all_wrappers():
    """Smoke test: each Step 2 wrapper returns correctly-parsed Pydantic models from seeded data."""
    seeded_event = build_valid_event(event_id="evt-smoke-1", outcome_type="upset_victory")
    past_event = build_valid_event(event_id="evt-smoke-past", outcome_type="upset_victory")
    player = build_valid_player(team="Argentina")
    narrative = build_valid_event_narrative(event_id="evt-smoke-1")

    agg_docs = [
        {"_id": "poster", "total_orders": 100, "total_impressions": 5000, "count": 2},
    ]

    mock_client = _MockMCPClient()
    mock_client.register("find", "events", _make_event_find_handler(seeded_event, [past_event]))
    mock_client.register("find", "player_context", [player.model_dump(mode="json")])
    mock_client.register("aggregate", "performance", agg_docs)

    import unittest.mock as mock
    with (
        mock.patch("src.db.events.get_client", return_value=mock_client),
        mock.patch("src.db.performance.get_client", return_value=mock_client),
        mock.patch("src.db.player_context.get_client", return_value=mock_client),
    ):
        from src.db.events import (
            find_past_events_by_outcome,
            get_event,
            update_event_narrative,
        )
        from src.db.performance import aggregate_performance_for_events
        from src.db.player_context import find_players_for_teams

        # get_event → returns the seeded event
        result_event = await get_event("evt-smoke-1")
        assert result_event is not None
        assert result_event.event_id == "evt-smoke-1"

        # find_past_events_by_outcome → returns past events
        past_results = await find_past_events_by_outcome("upset_victory", "evt-smoke-1")
        assert len(past_results) == 1
        assert past_results[0].event_id == "evt-smoke-past"

        # aggregate_performance_for_events → surfaces top_product_route
        perf = await aggregate_performance_for_events(["evt-smoke-past"])
        assert perf["top_product_route"] == "poster"
        assert perf["total_orders"] == 100
        assert perf["past_event_count"] == 1

        # find_players_for_teams → returns player list
        players = await find_players_for_teams("Argentina", "France")
        assert len(players) == 1
        assert players[0].name == "Lionel Messi"

        # update_event_narrative → call is recorded in mock_client.calls
        await update_event_narrative("evt-smoke-1", narrative)

    # Assert update-many call shape is captured verbatim
    update_calls = [
        (tn, args)
        for tn, args in mock_client.calls
        if tn == "update-many" and args.get("collection") == "events"
    ]
    assert len(update_calls) == 1
    update_args = update_calls[0][1]
    assert update_args["filter"] == {"event_id": "evt-smoke-1"}
    assert "event_narrative" in update_args["update"]["$set"]
    assert update_args["update"]["$set"]["event_narrative"] == narrative.model_dump(mode="json")


@pytest.mark.anyio
async def test_mock_dispatch_vector_search():
    """register_vector_search dispatches $vectorSearch aggregates correctly."""
    sa = build_valid_similar_asset()
    sa_doc = sa.model_dump(mode="json")

    mock_client = _MockMCPClient()
    mock_client.register_vector_search(collection="assets", results=[sa_doc])

    import unittest.mock as mock
    with mock.patch("src.db.assets.get_client", return_value=mock_client):
        from src.db.assets import vector_search_assets

        result = await vector_search_assets(build_embedding_fixture())

    assert len(result) == 1
    assert result[0].asset_id == sa.asset_id
    assert result[0].similarity == sa.similarity


@pytest.mark.anyio
async def test_mock_dispatch_falls_back_to_collection_key():
    """aggregate on performance still dispatches via collection key when no $vectorSearch registered."""
    agg_docs = [{"_id": "poster", "total_orders": 50, "total_impressions": 2000, "count": 1}]

    mock_client = _MockMCPClient()
    mock_client.register("aggregate", "performance", agg_docs)

    import unittest.mock as mock
    with mock.patch("src.db.performance.get_client", return_value=mock_client):
        from src.db.performance import aggregate_performance_for_events

        result = await aggregate_performance_for_events(["evt-past-1"])

    assert result["top_product_route"] == "poster"
    assert result["total_orders"] == 50


def test_embedding_helper_is_patched_in_runner():
    """build_runner_with_mock_db patches _compute_image_embedding to return the fixture."""
    import unittest.mock as mock
    import src.capabilities.similarity as sim_module

    with build_runner_with_mock_db():
        patched_fn = sim_module._compute_image_embedding
        # The patch replaces the function — calling it should return build_embedding_fixture()
        result = patched_fn("anything")

    assert isinstance(result, list)
    assert len(result) == 3072


# ---------------------------------------------------------------------------
# Step 6 scaffolding smoke tests (T-6.11)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_step6_assets_handler_returns_route_spanning_queued_assets():
    """_make_step6_assets_find_handler returns correct corpus for each filter shape."""
    import unittest.mock as mock
    from src.db.assets import get_assets_for_event

    mock_client = _MockMCPClient()
    mock_client.register("find", "assets", _make_step6_assets_find_handler())

    with mock.patch("src.db.assets.get_client", return_value=mock_client):
        # status="scored" → pre-seeded route-spanning assets
        scored = await get_assets_for_event("evt-demo-1", status="scored")

    asset_ids = {a.asset_id for a in scored}
    assert STEP6_QUEUED_IDS <= asset_ids, "All queued asset IDs must be present"
    assert STEP6_UNSURFACED_ID in asset_ids, "Un-surfaced asset must be present"

    # Route span: poster, tshirt, social_only all present among queued
    queued = [a for a in scored if a.queue_type is not None]
    routes = {a.product_route for a in queued}
    assert "poster" in routes
    assert "tshirt" in routes
    assert "social_only" in routes

    # Un-surfaced asset has queue_type=None
    unsurfaced = next(a for a in scored if a.asset_id == STEP6_UNSURFACED_ID)
    assert unsurfaced.queue_type is None

    # Crowd shot has empty detected_subjects
    crowd = next(a for a in scored if a.asset_id == STEP6_CROWD_ASSET_ID)
    assert crowd.detected_subjects == []


@pytest.mark.anyio
async def test_step6_assets_handler_no_status_returns_base_corpus():
    """_make_step6_assets_find_handler falls back to Step 5 base corpus for no-status queries."""
    import unittest.mock as mock
    from src.db.assets import get_assets_for_event

    mock_client = _MockMCPClient()
    mock_client.register("find", "assets", _make_step6_assets_find_handler())

    with mock.patch("src.db.assets.get_client", return_value=mock_client):
        all_assets = await get_assets_for_event("evt-demo-1")

    # Step 5 base corpus is 4 assets (ast-0 through ast-3)
    assert len(all_assets) == 4


def test_patch_draft_copy_for_asset_round_trips():
    """patch_draft_copy_for_asset returns the canned copy when set."""
    from src.capabilities.drafts import _draft_copy_for_asset

    with patch_draft_copy_for_asset(_CANNED_COPY):
        import src.capabilities.drafts as drafts_module
        result = drafts_module._draft_copy_for_asset({}, {})

    assert result.headline == _CANNED_COPY.headline
    assert result.hashtags == _CANNED_COPY.hashtags
