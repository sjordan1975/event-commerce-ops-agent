"""Smoke test: verify _MockMCPClient dispatch correctly seeds all Step 2 wrapper calls.

Does NOT run the agent — exercises wrappers directly against the mock client to
confirm the envelope encoding matches what each wrapper's parse logic expects.
"""

import pytest

from tests.conftest import build_valid_event, build_valid_event_narrative, build_valid_player
from tests.evals.conftest import _MockMCPClient


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
