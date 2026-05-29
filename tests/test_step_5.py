"""Tests for Step 5: propose_review_queue capability."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.errors import PreconditionError
from src.models import QueueItem, ReviewQueue


# ---------------------------------------------------------------------------
# T-5.4: save_queue_assignment unit tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_save_queue_assignment_sets_correct_fields():
    """update-many invoked with correct filter and $set containing the four queue fields."""
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

    with patch("src.db.assets.get_client", return_value=mock_client):
        from src.db.assets import save_queue_assignment
        await save_queue_assignment(
            asset_id="ast-001",
            queue_type="exploitation",
            product_route="poster",
            rank=1,
            rationale="features the key figure",
        )

    mock_client.call.assert_called_once()
    call_args = mock_client.call.call_args
    tool_name = call_args[0][0]
    args = call_args[0][1]

    assert tool_name == "update-many"
    assert args["database"] == "event_commerce"
    assert args["collection"] == "assets"
    assert args["filter"] == {"asset_id": "ast-001"}

    set_block = args["update"]["$set"]
    assert set_block["queue_type"] == "exploitation"
    assert set_block["product_route"] == "poster"
    assert set_block["queue_rank"] == 1
    assert set_block["queue_rationale"] == "features the key figure"


@pytest.mark.anyio
async def test_save_queue_assignment_no_status_key():
    """$set must not contain a status key — queue assignment does not change status."""
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

    with patch("src.db.assets.get_client", return_value=mock_client):
        from src.db.assets import save_queue_assignment
        await save_queue_assignment(
            asset_id="ast-002",
            queue_type="discovery",
            product_route=None,
            rank=2,
            rationale="worth surfacing",
        )

    call_args = mock_client.call.call_args
    set_block = call_args[0][1]["update"]["$set"]
    assert "status" not in set_block


@pytest.mark.anyio
async def test_save_queue_assignment_null_product_route():
    """product_route=None is a valid discovery assignment."""
    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

    with patch("src.db.assets.get_client", return_value=mock_client):
        from src.db.assets import save_queue_assignment
        await save_queue_assignment(
            asset_id="ast-003",
            queue_type="discovery",
            product_route=None,
            rank=1,
            rationale="no route yet",
        )

    call_args = mock_client.call.call_args
    set_block = call_args[0][1]["update"]["$set"]
    assert set_block["product_route"] is None
    assert set_block["queue_type"] == "discovery"


# ---------------------------------------------------------------------------
# T-5.5: prepare_queue_candidates unit tests
# ---------------------------------------------------------------------------

def _make_similarity_results(assets):
    """Build a list of similarity_results dicts (as stored in ctx.state)."""
    return [
        {
            "asset_id": a["asset_id"],
            "neighbors": a.get("neighbors", []),
            "inferred_route": a.get("inferred_route", None),
        }
        for a in assets
    ]


def _make_scored_assets(assets):
    """Build a list of scored_assets dicts (as stored in ctx.state)."""
    return [
        {
            "asset_id": a["asset_id"],
            "scores": a.get("scores", {"quality_score": 0.7, "merch_score": 0.7, "emotional_score": 0.7, "social_score": 0.7, "identity_score": 0.7}),
            "detected_subjects": a.get("detected_subjects", []),
        }
        for a in assets
    ]


def test_prepare_queue_candidates_cutoff_boundary():
    """top_similarity == cutoff goes to exploitation; just below goes to discovery."""
    from src.capabilities.queue import prepare_queue_candidates

    cutoff = 0.75

    sim_results = _make_similarity_results([
        {"asset_id": "a1", "neighbors": [{"asset_id": "p1", "event_id": "e1", "similarity": 0.75, "product_route": "poster", "scores": None}], "inferred_route": "poster"},
        {"asset_id": "a2", "neighbors": [{"asset_id": "p2", "event_id": "e1", "similarity": 0.74, "product_route": "tshirt", "scores": None}], "inferred_route": "tshirt"},
    ])
    scored = _make_scored_assets([
        {"asset_id": "a1"},
        {"asset_id": "a2"},
    ])
    narrative = {"event_id": "evt-001", "narrative_angle": "test"}

    result = prepare_queue_candidates(sim_results, scored, narrative, cutoff)

    expl_ids = [c["asset_id"] for c in result["exploitation"]]
    disc_ids = [c["asset_id"] for c in result["discovery"]]
    assert "a1" in expl_ids, "asset at exact cutoff should be exploitation"
    assert "a2" in disc_ids, "asset just below cutoff should be discovery"


def test_prepare_queue_candidates_empty_neighbors_is_discovery():
    """Assets with no neighbors have top_similarity=0.0 → discovery."""
    from src.capabilities.queue import prepare_queue_candidates

    sim_results = _make_similarity_results([
        {"asset_id": "a1", "neighbors": [], "inferred_route": None},
    ])
    scored = _make_scored_assets([{"asset_id": "a1"}])
    narrative = {"event_id": "evt-001", "narrative_angle": "test"}

    result = prepare_queue_candidates(sim_results, scored, narrative, cutoff=0.75)

    assert len(result["exploitation"]) == 0
    assert len(result["discovery"]) == 1
    assert result["discovery"][0]["asset_id"] == "a1"


def test_prepare_queue_candidates_join_correctness():
    """Join attaches scores + detected_subjects from scored_assets to each candidate."""
    from src.capabilities.queue import prepare_queue_candidates

    scores = {"quality_score": 0.9, "merch_score": 0.8, "emotional_score": 0.7, "social_score": 0.6, "identity_score": 0.5}
    sim_results = _make_similarity_results([
        {"asset_id": "a1", "neighbors": [{"asset_id": "p1", "event_id": "e1", "similarity": 0.85, "product_route": "poster", "scores": None}], "inferred_route": "poster"},
    ])
    scored = [
        {"asset_id": "a1", "scores": scores, "detected_subjects": ["Lionel Messi"]},
    ]
    narrative = {"event_id": "evt-001", "narrative_angle": "test"}

    result = prepare_queue_candidates(sim_results, scored, narrative, cutoff=0.75)

    assert len(result["exploitation"]) == 1
    candidate = result["exploitation"][0]
    assert candidate["scores"] == scores
    assert candidate["detected_subjects"] == ["Lionel Messi"]


def test_prepare_queue_candidates_inferred_route_in_exploitation():
    """inferred_route is carried into exploitation candidates."""
    from src.capabilities.queue import prepare_queue_candidates

    sim_results = _make_similarity_results([
        {"asset_id": "a1", "neighbors": [{"asset_id": "p1", "event_id": "e1", "similarity": 0.9, "product_route": "poster", "scores": None}], "inferred_route": "poster"},
    ])
    scored = _make_scored_assets([{"asset_id": "a1"}])
    narrative = {"event_id": "evt-001", "narrative_angle": "test"}

    result = prepare_queue_candidates(sim_results, scored, narrative, cutoff=0.75)

    assert result["exploitation"][0]["inferred_route"] == "poster"


def test_prepare_queue_candidates_precondition_no_similarity():
    """Raises PreconditionError when similarity_results is empty."""
    from src.capabilities.queue import prepare_queue_candidates

    scored = _make_scored_assets([{"asset_id": "a1"}])
    narrative = {"event_id": "evt-001", "narrative_angle": "test"}

    with pytest.raises(PreconditionError) as exc_info:
        prepare_queue_candidates([], scored, narrative, cutoff=0.75)

    assert "similarity_results" in exc_info.value.missing


def test_prepare_queue_candidates_precondition_no_scored():
    """Raises PreconditionError when scored_assets is empty."""
    from src.capabilities.queue import prepare_queue_candidates

    sim_results = _make_similarity_results([{"asset_id": "a1", "neighbors": [], "inferred_route": None}])
    narrative = {"event_id": "evt-001", "narrative_angle": "test"}

    with pytest.raises(PreconditionError) as exc_info:
        prepare_queue_candidates(sim_results, [], narrative, cutoff=0.75)

    assert "scored_assets" in exc_info.value.missing


def test_prepare_queue_candidates_precondition_no_narrative():
    """Raises PreconditionError when event_narrative is None."""
    from src.capabilities.queue import prepare_queue_candidates

    sim_results = _make_similarity_results([{"asset_id": "a1", "neighbors": [], "inferred_route": None}])
    scored = _make_scored_assets([{"asset_id": "a1"}])

    with pytest.raises(PreconditionError) as exc_info:
        prepare_queue_candidates(sim_results, scored, None, cutoff=0.75)

    assert "event_narrative" in exc_info.value.missing


def test_prepare_queue_candidates_all_preconditions_one_error():
    """All missing inputs are reported in a single PreconditionError."""
    from src.capabilities.queue import prepare_queue_candidates

    with pytest.raises(PreconditionError) as exc_info:
        prepare_queue_candidates([], [], None, cutoff=0.75)

    missing = exc_info.value.missing
    assert "similarity_results" in missing
    assert "scored_assets" in missing
    assert "event_narrative" in missing


# ---------------------------------------------------------------------------
# T-5.7: queue_instruction_provider unit tests
# ---------------------------------------------------------------------------

class _FakeContext:
    """Minimal fake ReadonlyContext exposing .state."""
    def __init__(self, state: dict):
        self.state = state


def test_queue_instruction_provider_builds_prompt():
    """Provider embeds narrative angle, key-figure names, and both pool asset_ids."""
    from src.capabilities.queue import queue_instruction_provider

    state = {
        "event_narrative": {
            "event_id": "evt-demo-1",
            "narrative_angle": "Messi crowns legendary career",
            "key_figures": [
                {"name": "Lionel Messi", "team": "Argentina", "relevance": "scored the penalty",
                 "grounded_facts": [], "commercial_signal": "high"},
            ],
            "commercial_timing": "Aggressive",
            "historical_baseline": {
                "outcome_type": "upset_victory", "past_event_count": 3,
                "top_product_route": "poster", "total_orders": 450,
                "total_impressions": 22000, "notes": "test",
            },
        },
        "queue_candidates": {
            "exploitation": [
                {"asset_id": "a1", "top_similarity": 0.91, "inferred_route": "poster",
                 "scores": {"quality_score": 0.9}, "detected_subjects": ["Lionel Messi"]},
            ],
            "discovery": [
                {"asset_id": "a3", "top_similarity": 0.31, "inferred_route": None,
                 "scores": {"emotional_score": 0.92}, "detected_subjects": ["Lionel Messi"]},
            ],
        },
    }

    ctx = _FakeContext(state)
    result = queue_instruction_provider(ctx)

    assert "Messi crowns legendary career" in result
    assert "Lionel Messi" in result
    assert "a1" in result
    assert "a3" in result


# ---------------------------------------------------------------------------
# T-5.8: build_review_queue_node + _queue_model_callback unit tests
# ---------------------------------------------------------------------------

def test_build_review_queue_node_attributes():
    """LlmAgent node has correct name, mode, output_key."""
    from src.capabilities.queue import build_review_queue_node

    node = build_review_queue_node()
    assert node.name == "propose_review_queue"
    assert node.output_key == "review_queue"


def test_queue_model_callback_returns_none_when_no_fixture():
    """Callback returns None (live model path) when _FIXTURE_RESPONSE is None."""
    import src.capabilities.queue as queue_module
    from src.capabilities.queue import _queue_model_callback

    original = queue_module._FIXTURE_RESPONSE
    try:
        queue_module._FIXTURE_RESPONSE = None
        result = _queue_model_callback(MagicMock(), MagicMock())
        assert result is None
    finally:
        queue_module._FIXTURE_RESPONSE = original


def test_queue_model_callback_returns_llm_response_when_fixture_set():
    """Callback returns an LlmResponse whose text parses into ReviewQueue when fixture is set."""
    import src.capabilities.queue as queue_module
    from src.capabilities.queue import _queue_model_callback
    from google.adk.models.llm_response import LlmResponse

    fixture = {
        "event_id": "evt-demo-1",
        "exploitation": [
            {"asset_id": "a1", "queue_type": "exploitation", "rank": 1,
             "product_route": "poster", "rationale": "key figure"},
        ],
        "discovery": [
            {"asset_id": "a3", "queue_type": "discovery", "rank": 1,
             "product_route": "social_only", "rationale": "worth it"},
        ],
        "strategy_summary": "test summary",
    }

    original = queue_module._FIXTURE_RESPONSE
    try:
        queue_module._FIXTURE_RESPONSE = fixture
        result = _queue_model_callback(MagicMock(), MagicMock())
        assert isinstance(result, LlmResponse)
        # The text should parse into ReviewQueue
        text = result.content.parts[0].text
        parsed = ReviewQueue.model_validate(json.loads(text))
        assert parsed.event_id == "evt-demo-1"
        assert parsed.exploitation[0].asset_id == "a1"
    finally:
        queue_module._FIXTURE_RESPONSE = original


# ---------------------------------------------------------------------------
# T-5.9: persist_review_queue unit tests
# ---------------------------------------------------------------------------

def _make_fake_ctx(review_queue: dict, queue_candidates: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = {
        "review_queue": review_queue,
        "queue_candidates": queue_candidates,
    }
    return ctx


@pytest.mark.anyio
async def test_persist_review_queue_exploitation_uses_mechanical_route():
    """Exploitation items are persisted with the inferred_route from prepare (not LLM route)."""
    from src.capabilities.queue import persist_review_queue

    review_queue = {
        "event_id": "evt-demo-1",
        "exploitation": [
            {"asset_id": "a1", "queue_type": "exploitation", "rank": 1,
             "product_route": "tshirt",  # LLM chose tshirt — should be ignored
             "rationale": "key figure"},
        ],
        "discovery": [],
        "strategy_summary": "test",
    }
    queue_candidates = {
        "exploitation": [
            {"asset_id": "a1", "inferred_route": "poster"},  # mechanical route
        ],
        "discovery": [],
    }

    with patch("src.capabilities.queue.save_queue_assignment", new_callable=AsyncMock) as mock_save:
        result = await persist_review_queue(_make_fake_ctx(review_queue, queue_candidates))

    mock_save.assert_called_once_with("a1", "exploitation", "poster", 1, "key figure")
    assert result["membership_violations"] == []


@pytest.mark.anyio
async def test_persist_review_queue_discovery_uses_llm_route():
    """Discovery items are persisted with the LLM's chosen product_route."""
    from src.capabilities.queue import persist_review_queue

    review_queue = {
        "event_id": "evt-demo-1",
        "exploitation": [],
        "discovery": [
            {"asset_id": "a3", "queue_type": "discovery", "rank": 1,
             "product_route": "social_only",
             "rationale": "worth surfacing"},
        ],
        "strategy_summary": "test",
    }
    queue_candidates = {
        "exploitation": [],
        "discovery": [
            {"asset_id": "a3", "inferred_route": None},
        ],
    }

    with patch("src.capabilities.queue.save_queue_assignment", new_callable=AsyncMock) as mock_save:
        result = await persist_review_queue(_make_fake_ctx(review_queue, queue_candidates))

    mock_save.assert_called_once_with("a3", "discovery", "social_only", 1, "worth surfacing")
    assert result["membership_violations"] == []


@pytest.mark.anyio
async def test_persist_review_queue_unsurfaced_assets_not_saved():
    """Discovery-pool assets not surfaced by the LLM get no save_queue_assignment call."""
    from src.capabilities.queue import persist_review_queue

    review_queue = {
        "event_id": "evt-demo-1",
        "exploitation": [],
        "discovery": [
            {"asset_id": "a3", "queue_type": "discovery", "rank": 1,
             "product_route": "social_only", "rationale": "worth it"},
        ],
        "strategy_summary": "test",
    }
    queue_candidates = {
        "exploitation": [],
        "discovery": [
            {"asset_id": "a3", "inferred_route": None},
            {"asset_id": "a4", "inferred_route": None},  # a4 not surfaced by LLM
        ],
    }

    with patch("src.capabilities.queue.save_queue_assignment", new_callable=AsyncMock) as mock_save:
        result = await persist_review_queue(_make_fake_ctx(review_queue, queue_candidates))

    # Only a3 should be saved, not a4
    saved_ids = [call.args[0] for call in mock_save.call_args_list]
    assert "a4" not in saved_ids
    assert "a3" in saved_ids


@pytest.mark.anyio
async def test_persist_review_queue_cross_assigned_recorded_as_violation():
    """Cross-assigned asset (discovery asset placed in exploitation) is recorded as violation, not raised."""
    from src.capabilities.queue import persist_review_queue

    review_queue = {
        "event_id": "evt-demo-1",
        "exploitation": [
            {"asset_id": "a3", "queue_type": "exploitation", "rank": 1,
             "product_route": "poster", "rationale": "cross-assigned"},
        ],
        "discovery": [],
        "strategy_summary": "test",
    }
    # a3 is in discovery pool, not in exploitation candidates
    queue_candidates = {
        "exploitation": [
            {"asset_id": "a1", "inferred_route": "poster"},
        ],
        "discovery": [
            {"asset_id": "a3", "inferred_route": None},
        ],
    }

    with patch("src.capabilities.queue.save_queue_assignment", new_callable=AsyncMock) as mock_save:
        result = await persist_review_queue(_make_fake_ctx(review_queue, queue_candidates))

    # Should not have raised; a3 recorded as violation
    violations = result["membership_violations"]
    assert len(violations) == 1
    assert "a3" in str(violations[0])
    # No save called for the cross-assigned item
    saved_ids = [call.args[0] for call in mock_save.call_args_list]
    assert "a3" not in saved_ids


# ---------------------------------------------------------------------------
# T-5.10: node adapter unit tests
# ---------------------------------------------------------------------------

def test_node_adapter_names():
    """All three nodes are importable with the expected names."""
    from src.capabilities import (
        prepare_queue_candidates_node,
        persist_review_queue_node,
        propose_review_queue_node,
    )
    assert prepare_queue_candidates_node.name == "prepare_queue_candidates"
    assert persist_review_queue_node.name == "persist_review_queue"
    assert propose_review_queue_node.name == "propose_review_queue"


@pytest.mark.anyio
async def test_node_adapter_prepare_writes_state():
    """_node_prepare_queue_candidates writes queue_candidates to ctx.state."""
    from src.capabilities import _node_prepare_queue_candidates

    ctx = MagicMock()
    ctx.state = {
        "similarity_results": [
            {"asset_id": "a1", "neighbors": [{"asset_id": "p1", "event_id": "e1", "similarity": 0.9, "product_route": "poster", "scores": None}], "inferred_route": "poster"},
        ],
        "scored_assets": [
            {"asset_id": "a1", "scores": {"quality_score": 0.8, "merch_score": 0.7, "emotional_score": 0.7, "social_score": 0.7, "identity_score": 0.7}, "detected_subjects": []},
        ],
        "event_narrative": {"event_id": "evt-001", "narrative_angle": "test", "key_figures": []},
        "QUEUE_EXPLOITATION_SIMILARITY_CUTOFF": "0.75",
    }

    result = await _node_prepare_queue_candidates(ctx)
    assert "queue_candidates" in ctx.state
    candidates = ctx.state["queue_candidates"]
    assert "exploitation" in candidates
    assert "discovery" in candidates


@pytest.mark.anyio
async def test_node_adapter_persist_writes_state():
    """_node_persist_review_queue writes review_queue back to ctx.state."""
    from src.capabilities import _node_persist_review_queue

    ctx = MagicMock()
    ctx.state = {
        "review_queue": {
            "event_id": "evt-demo-1",
            "exploitation": [
                {"asset_id": "a1", "queue_type": "exploitation", "rank": 1,
                 "product_route": "poster", "rationale": "key figure"},
            ],
            "discovery": [],
            "strategy_summary": "test",
        },
        "queue_candidates": {
            "exploitation": [{"asset_id": "a1", "inferred_route": "poster"}],
            "discovery": [],
        },
    }

    with patch("src.capabilities.queue.save_queue_assignment", new_callable=AsyncMock):
        result = await _node_persist_review_queue(ctx)

    assert "review_queue" in ctx.state
