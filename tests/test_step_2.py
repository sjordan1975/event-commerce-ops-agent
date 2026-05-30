"""Unit tests for Step 2: db wrappers and build_event_context capability."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.errors import PreconditionError
from src.models import Event, EventNarrative, HistoricalBaseline, KeyFigure, Player
from tests.conftest import build_valid_event, build_valid_event_narrative, build_valid_player


# ---------------------------------------------------------------------------
# Envelope helpers (mirrors the real MCP shape documented in src/db/__init__.py)
# ---------------------------------------------------------------------------

def _make_find_envelope(docs: list[dict]) -> dict:
    """Build a mock MCP envelope matching the real MongoDB MCP find/aggregate shape."""
    if not docs:
        return {"content": [{"type": "text", "text": "Query resulted in 0 documents."}]}
    uid = "mock-uuid-1234"
    data_text = (
        f"Summary text.\n\n"
        f"<untrusted-user-data-{uid}>\n"
        f"{json.dumps(docs)}\n"
        f"</untrusted-user-data-{uid}>\n"
        f"Use the information above to respond."
    )
    return {
        "content": [
            {"type": "text", "text": "Query resulted in N documents."},
            {"type": "text", "text": data_text},
        ]
    }


# ---------------------------------------------------------------------------
# T-2.5: get_event
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_event():
    event = build_valid_event(event_id="evt-abc")
    event_doc = event.model_dump(mode="json")
    mock_client = AsyncMock()

    # Returns Event on match
    mock_client.call.return_value = _make_find_envelope([event_doc])
    with patch("src.db.events.get_client", return_value=mock_client):
        from src.db.events import get_event
        result = await get_event("evt-abc")

    assert isinstance(result, Event)
    assert result.event_id == "evt-abc"
    call_args = mock_client.call.call_args
    assert call_args[0][0] == "find"
    assert call_args[0][1]["collection"] == "events"
    assert call_args[0][1]["filter"] == {"event_id": "evt-abc"}

    # Returns None on empty result
    mock_client.call.return_value = _make_find_envelope([])
    with patch("src.db.events.get_client", return_value=mock_client):
        result_none = await get_event("does-not-exist")
    assert result_none is None


# ---------------------------------------------------------------------------
# T-2.6: find_past_events_by_outcome
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_find_past_events_by_outcome():
    e1 = build_valid_event(event_id="evt-past-1", outcome_type="upset_victory")
    e2 = build_valid_event(event_id="evt-past-2", outcome_type="upset_victory")
    mock_client = AsyncMock()

    mock_client.call.return_value = _make_find_envelope(
        [e1.model_dump(mode="json"), e2.model_dump(mode="json")]
    )
    with patch("src.db.events.get_client", return_value=mock_client):
        from src.db.events import find_past_events_by_outcome
        results = await find_past_events_by_outcome("upset_victory", "evt-current")

    assert len(results) == 2
    assert all(isinstance(r, Event) for r in results)
    call_args = mock_client.call.call_args
    assert call_args[0][0] == "find"
    assert call_args[0][1]["filter"]["outcome_type"] == "upset_victory"
    assert call_args[0][1]["filter"]["event_id"] == {"$ne": "evt-current"}

    # Empty result returns []
    mock_client.call.return_value = _make_find_envelope([])
    with patch("src.db.events.get_client", return_value=mock_client):
        empty = await find_past_events_by_outcome("draw", "evt-current")
    assert empty == []


# ---------------------------------------------------------------------------
# T-2.7: update_event_narrative
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_update_event_narrative():
    narrative = build_valid_event_narrative(event_id="evt-xyz")
    mock_client = AsyncMock()
    mock_client.call.return_value = {"content": [{"type": "text", "text": "ok"}]}

    with patch("src.db.events.get_client", return_value=mock_client):
        from src.db.events import update_event_narrative
        await update_event_narrative("evt-xyz", narrative)

    call_args = mock_client.call.call_args
    assert call_args[0][0] == "update-many"
    args = call_args[0][1]
    assert args["collection"] == "events"
    assert args["filter"] == {"event_id": "evt-xyz"}
    assert args["update"]["$set"]["event_narrative"] == narrative.model_dump(mode="json")


# ---------------------------------------------------------------------------
# T-2.8: aggregate_performance_for_events
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_aggregate_performance_empty_event_ids():
    """Empty event_ids → zeroed baseline without any MCP call."""
    mock_client = AsyncMock()
    with patch("src.db.performance.get_client", return_value=mock_client):
        from src.db.performance import aggregate_performance_for_events
        result = await aggregate_performance_for_events([])

    assert result["past_event_count"] == 0
    assert result["top_product_route"] is None
    assert result["total_orders"] == 0
    assert result["total_impressions"] == 0
    mock_client.call.assert_not_called()


@pytest.mark.anyio
async def test_aggregate_performance_no_docs():
    """No performance docs found → zeroed baseline with correct past_event_count."""
    mock_client = AsyncMock()
    mock_client.call.return_value = _make_find_envelope([])

    with patch("src.db.performance.get_client", return_value=mock_client):
        from src.db.performance import aggregate_performance_for_events
        result = await aggregate_performance_for_events(["evt-1", "evt-2"])

    assert result["past_event_count"] == 2
    assert result["top_product_route"] is None
    assert result["total_orders"] == 0

    call_args = mock_client.call.call_args
    assert call_args[0][0] == "aggregate"
    assert call_args[0][1]["collection"] == "performance"
    pipeline = call_args[0][1]["pipeline"]
    # Spine fix (T-8.4) adds a leading $match{metrics_status:$ne pending_sync} stage;
    # the event_id $match follows it. Locate it by content, not by index.
    event_id_matches = [s for s in pipeline if "$match" in s and "event_id" in s["$match"]]
    assert event_id_matches, "event_id $match stage missing from pipeline"
    assert event_id_matches[0]["$match"]["event_id"]["$in"] == ["evt-1", "evt-2"]
    # Spine fix stage must be present
    spine_matches = [s for s in pipeline if "$match" in s and "metrics_status" in s.get("$match", {})]
    assert spine_matches, "spine fix $match stage missing — pending docs could dilute baseline"


@pytest.mark.anyio
async def test_aggregate_performance_with_results():
    """Populated aggregate result → correct top_product_route and totals."""
    agg_docs = [
        {"_id": "poster", "total_orders": 200, "total_impressions": 10000, "count": 5},
        {"_id": "tshirt", "total_orders": 80, "total_impressions": 4000, "count": 3},
    ]
    mock_client = AsyncMock()
    mock_client.call.return_value = _make_find_envelope(agg_docs)

    with patch("src.db.performance.get_client", return_value=mock_client):
        from src.db.performance import aggregate_performance_for_events
        result = await aggregate_performance_for_events(["evt-1"])

    assert result["past_event_count"] == 1
    assert result["top_product_route"] == "poster"
    assert result["total_orders"] == 280
    assert result["total_impressions"] == 14000
    assert result["asset_count"] == 8


# ---------------------------------------------------------------------------
# T-2.9: find_players_for_teams
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_find_players_for_teams():
    p1 = build_valid_player(name="Messi", team="Argentina")
    p2 = build_valid_player(player_id="p2", name="Mbappe", team="France")
    mock_client = AsyncMock()
    mock_client.call.return_value = _make_find_envelope(
        [p1.model_dump(mode="json"), p2.model_dump(mode="json")]
    )

    with patch("src.db.player_context.get_client", return_value=mock_client):
        from src.db.player_context import find_players_for_teams
        results = await find_players_for_teams("Argentina", "France")

    assert len(results) == 2
    assert all(isinstance(r, Player) for r in results)
    call_args = mock_client.call.call_args
    assert call_args[0][0] == "find"
    assert call_args[0][1]["collection"] == "player_context"
    assert call_args[0][1]["filter"] == {"team": {"$in": ["Argentina", "France"]}}

    # Empty result returns []
    mock_client.call.return_value = _make_find_envelope([])
    with patch("src.db.player_context.get_client", return_value=mock_client):
        empty = await find_players_for_teams("Unknown", "Team")
    assert empty == []


# ---------------------------------------------------------------------------
# T-2.11: _run_narrative_llm
# ---------------------------------------------------------------------------

def test_run_narrative_llm():
    from src.capabilities.context import _run_narrative_llm

    expected = build_valid_event_narrative()
    fake_response = MagicMock()
    fake_response.text = expected.model_dump_json()

    fake_model_api = MagicMock()
    fake_model_api.generate_content.return_value = fake_response

    fake_client_instance = MagicMock()
    fake_client_instance.models = fake_model_api

    with (
        patch("src.capabilities.context.genai.Client", return_value=fake_client_instance),
        patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key", "GEMINI_NARRATIVE_MODEL": "gemini-test"}),
    ):
        result = _run_narrative_llm("test prompt", EventNarrative)

    assert isinstance(result, EventNarrative)
    call_kwargs = fake_model_api.generate_content.call_args
    assert call_kwargs[1]["model"] == "gemini-test"
    assert call_kwargs[1]["contents"] == "test prompt"
    config = call_kwargs[1]["config"]
    assert config.response_schema == EventNarrative


# ---------------------------------------------------------------------------
# T-2.12: build_event_context capability
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_build_event_context_raises_when_event_missing():
    with patch("src.capabilities.context.get_event", new_callable=AsyncMock, return_value=None):
        from src.capabilities.context import build_event_context
        with pytest.raises(PreconditionError) as exc_info:
            await build_event_context("evt-missing")
    err = exc_info.value
    assert err.capability == "build_event_context"
    assert err.context == "evt-missing"
    assert "event" in err.missing


@pytest.mark.anyio
async def test_build_event_context_orchestration():
    """Happy path: correct call order + correct return dict shape."""
    event = build_valid_event(event_id="evt-demo")
    past = [build_valid_event(event_id="evt-past", outcome_type="upset_victory")]
    narrative = build_valid_event_narrative(event_id="evt-demo")

    with (
        patch("src.capabilities.context.get_event", new_callable=AsyncMock, return_value=event),
        patch("src.capabilities.context.find_past_events_by_outcome", new_callable=AsyncMock, return_value=past),
        patch("src.capabilities.context.aggregate_performance_for_events", new_callable=AsyncMock,
              return_value={"past_event_count": 1, "top_product_route": "poster",
                            "total_orders": 100, "total_impressions": 5000, "asset_count": 3}),
        patch("src.capabilities.context.find_players_for_teams", new_callable=AsyncMock,
              return_value=[build_valid_player()]),
        patch("src.capabilities.context._run_narrative_llm", return_value=narrative),
        patch("src.capabilities.context.update_event_narrative", new_callable=AsyncMock) as mock_update,
    ):
        from src.capabilities.context import build_event_context
        result = await build_event_context("evt-demo")

    # Returns correct dict shape
    assert set(result.keys()) >= {"event_id", "narrative_angle", "key_figures",
                                   "commercial_timing", "historical_baseline"}
    assert result == narrative.model_dump(mode="json")

    # update_event_narrative called with correct args
    mock_update.assert_called_once_with("evt-demo", narrative)


@pytest.mark.anyio
async def test_build_event_context_empty_cohort():
    """No past events → baseline has past_event_count=0, top_product_route=None; LLM still called."""
    event = build_valid_event(event_id="evt-new")
    narrative = build_valid_event_narrative(event_id="evt-new")

    with (
        patch("src.capabilities.context.get_event", new_callable=AsyncMock, return_value=event),
        patch("src.capabilities.context.find_past_events_by_outcome", new_callable=AsyncMock, return_value=[]),
        patch("src.capabilities.context.aggregate_performance_for_events", new_callable=AsyncMock,
              return_value={"past_event_count": 0, "top_product_route": None,
                            "total_orders": 0, "total_impressions": 0, "asset_count": 0}),
        patch("src.capabilities.context.find_players_for_teams", new_callable=AsyncMock, return_value=[]),
        patch("src.capabilities.context._run_narrative_llm", return_value=narrative) as mock_llm,
        patch("src.capabilities.context.update_event_narrative", new_callable=AsyncMock),
    ):
        from src.capabilities.context import build_event_context
        result = await build_event_context("evt-new")

    # LLM still called
    mock_llm.assert_called_once()
    # Prompt contains the empty-cohort branch text
    prompt_arg = mock_llm.call_args[0][0]
    assert "no past events" in prompt_arg.lower()
    # Result is still the narrative dict
    assert result == narrative.model_dump(mode="json")


@pytest.mark.anyio
async def test_build_event_context_empty_players():
    """No seeded players → prompt contains empty-players branch; capability still completes."""
    event = build_valid_event(event_id="evt-noplayers")
    narrative = build_valid_event_narrative(event_id="evt-noplayers")

    with (
        patch("src.capabilities.context.get_event", new_callable=AsyncMock, return_value=event),
        patch("src.capabilities.context.find_past_events_by_outcome", new_callable=AsyncMock,
              return_value=[build_valid_event(event_id="evt-past")]),
        patch("src.capabilities.context.aggregate_performance_for_events", new_callable=AsyncMock,
              return_value={"past_event_count": 1, "top_product_route": "poster",
                            "total_orders": 50, "total_impressions": 2000, "asset_count": 2}),
        patch("src.capabilities.context.find_players_for_teams", new_callable=AsyncMock, return_value=[]),
        patch("src.capabilities.context._run_narrative_llm", return_value=narrative) as mock_llm,
        patch("src.capabilities.context.update_event_narrative", new_callable=AsyncMock),
    ):
        from src.capabilities.context import build_event_context
        result = await build_event_context("evt-noplayers")

    prompt_arg = mock_llm.call_args[0][0]
    assert "no seeded players" in prompt_arg.lower()
    assert result == narrative.model_dump(mode="json")
