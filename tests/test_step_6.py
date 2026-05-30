"""Tests for Step 6: draft_campaigns_for_queue capability."""

import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Shared patch for get_edit_requested_campaigns — all Step 6 tests use the first-pass path
# (no edit_requested approvals exist yet; redraft is a Step 7 concern).
_NO_EDIT_REQUESTED = patch(
    "src.capabilities.drafts.get_edit_requested_campaigns",
    new_callable=AsyncMock,
    return_value=[],
)

import pytest

from src.models import Campaign, GeneratedCopy
from tests.conftest import build_valid_campaign, build_valid_generated_copy


# ---------------------------------------------------------------------------
# T-6.4: submit_campaign_for_review
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_submit_campaign_for_review():
    """Three writes issued with correct (database, collection); returns both ids."""
    from src.db.campaigns import submit_campaign_for_review

    mock_client = AsyncMock()
    mock_client.call = AsyncMock(return_value={"content": [{"type": "text", "text": "ok"}]})

    campaign = build_valid_campaign()

    with patch("src.db.campaigns.get_client", return_value=mock_client):
        result = await submit_campaign_for_review(campaign)

    calls = mock_client.call.call_args_list
    assert len(calls) == 3

    # Call 0: campaigns insert-many
    tool_name_0, args_0 = calls[0].args
    assert tool_name_0 == "insert-many"
    assert args_0["database"] == "event_commerce"
    assert args_0["collection"] == "campaigns"
    assert len(args_0["documents"]) == 1
    assert args_0["documents"][0]["campaign_id"] == campaign.campaign_id

    # Call 1: assets update-many — status + campaign_id only
    tool_name_1, args_1 = calls[1].args
    assert tool_name_1 == "update-many"
    assert args_1["database"] == "event_commerce"
    assert args_1["collection"] == "assets"
    assert args_1["filter"] == {"asset_id": campaign.asset_id}
    set_doc = args_1["update"]["$set"]
    assert set_doc == {"status": "campaign_draft_created", "campaign_id": campaign.campaign_id}

    # Call 2: approvals insert-many — pending, reviewer_notes=None, decided_at=None
    tool_name_2, args_2 = calls[2].args
    assert tool_name_2 == "insert-many"
    assert args_2["database"] == "event_commerce"
    assert args_2["collection"] == "approvals"
    approval_doc = args_2["documents"][0]
    assert approval_doc["status"] == "pending"
    assert approval_doc["reviewer_notes"] is None
    assert approval_doc["decided_at"] is None
    assert approval_doc["campaign_id"] == campaign.campaign_id
    assert approval_doc["asset_id"] == campaign.asset_id
    assert approval_doc["event_id"] == campaign.event_id

    # Returns both ids
    assert result["campaign_id"] == campaign.campaign_id
    assert "approval_id" in result
    assert result["approval_id"] == approval_doc["approval_id"]


def test_submit_campaign_for_review_no_reviewer_notes_param():
    """reviewer_notes must not be a parameter of submit_campaign_for_review."""
    from src.db.campaigns import submit_campaign_for_review
    sig = inspect.signature(submit_campaign_for_review)
    assert "reviewer_notes" not in sig.parameters


# ---------------------------------------------------------------------------
# T-6.5: _route_to_campaign_fields + _recommend_timing
# ---------------------------------------------------------------------------

def test_route_to_campaign_fields_poster():
    from src.capabilities.drafts import _route_to_campaign_fields
    product_type, platform = _route_to_campaign_fields("poster")
    assert product_type == "poster"
    assert platform == "shopify"


def test_route_to_campaign_fields_tshirt():
    from src.capabilities.drafts import _route_to_campaign_fields
    product_type, platform = _route_to_campaign_fields("tshirt")
    assert product_type == "tshirt"
    assert platform == "shopify"


def test_route_to_campaign_fields_social_only():
    from src.capabilities.drafts import _route_to_campaign_fields
    product_type, platform = _route_to_campaign_fields("social_only")
    assert product_type is None
    assert platform == "social"


def test_route_to_campaign_fields_none():
    from src.capabilities.drafts import _route_to_campaign_fields
    product_type, platform = _route_to_campaign_fields(None)
    assert product_type is None
    assert platform == "social"


def test_recommend_timing_deterministic(build_event):
    from src.capabilities.drafts import _recommend_timing
    event = build_event()
    t1 = _recommend_timing(0.9, event)
    t2 = _recommend_timing(0.9, event)
    assert t1 == t2


def test_recommend_timing_monotonic(build_event):
    """Higher timeliness → not later than lower timeliness."""
    from src.capabilities.drafts import _recommend_timing
    event = build_event()
    high = _recommend_timing(0.9, event)
    low = _recommend_timing(0.2, event)
    # sooner-or-equal ISO strings compare lexicographically for UTC datetimes
    assert high <= low


@pytest.fixture
def build_event():
    from tests.conftest import build_valid_event
    def _make(**overrides):
        return build_valid_event(**overrides)
    return _make


# ---------------------------------------------------------------------------
# T-6.7: _draft_copy_for_asset (internal helper + eval-mock seam)
# ---------------------------------------------------------------------------

def test_draft_copy_helper_prompt_construction():
    """Prompt contains narrative angle + detected subjects; response parsed correctly."""
    from src.capabilities.drafts import _draft_copy_for_asset

    canned_json = '{"headline": "Messi crowns legendary career", "caption": "Limited edition print.", "hashtags": ["#WC2026"]}'

    mock_response = MagicMock()
    mock_response.text = canned_json

    mock_models = MagicMock()
    mock_models.generate_content.return_value = mock_response

    mock_client_instance = MagicMock()
    mock_client_instance.models = mock_models

    with (
        patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}),
        patch("src.capabilities.drafts.genai") as mock_genai,
    ):
        mock_genai.Client.return_value = mock_client_instance
        result = _draft_copy_for_asset(
            narrative_context={"narrative_angle": "Messi crowns legendary career", "key_figures": "Lionel Messi"},
            item_context={"queue_rationale": "Identity match", "product_route": "poster", "detected_subjects": ["Lionel Messi"]},
        )

    # Verify the prompt contained narrative_angle and detected_subjects
    call_kwargs = mock_models.generate_content.call_args
    prompt_arg = call_kwargs.kwargs.get("contents") or call_kwargs.args[1]
    # contents is a list; find the string prompt
    if isinstance(prompt_arg, list):
        prompt_text = " ".join(str(p) for p in prompt_arg)
    else:
        prompt_text = str(prompt_arg)
    assert "Messi crowns legendary career" in prompt_text
    assert "Lionel Messi" in prompt_text

    assert isinstance(result, GeneratedCopy)
    assert result.headline == "Messi crowns legendary career"
    assert result.hashtags == ["#WC2026"]


# ---------------------------------------------------------------------------
# T-6.8: draft_campaigns_for_queue capability
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_draft_campaigns_one_draft_per_queued_asset():
    """One draft is created per surfaced asset; un-surfaced (queue_type=None) skipped."""
    from src.capabilities.drafts import draft_campaigns_for_queue
    from tests.conftest import build_valid_event, build_valid_event_narrative, build_valid_asset, build_valid_asset_scores

    event = build_valid_event(event_id="evt-demo-1", timeliness=0.9,
                              event_narrative=build_valid_event_narrative())
    asset_queued = build_valid_asset(
        asset_id="a1", event_id="evt-demo-1", status="scored",
        queue_type="exploitation", queue_rank=1, queue_rationale="Identity match",
        product_route="poster", detected_subjects=["Lionel Messi"],
        scores=build_valid_asset_scores(),
    )
    asset_unsurfaced = build_valid_asset(
        asset_id="a2", event_id="evt-demo-1", status="scored",
        queue_type=None, queue_rank=None, queue_rationale=None,
        product_route=None, detected_subjects=[],
        scores=build_valid_asset_scores(),
    )

    canned_copy = build_valid_generated_copy()

    with (
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts.get_assets_for_event", return_value=[asset_queued, asset_unsurfaced]),
        patch("src.capabilities.drafts._draft_copy_for_asset", return_value=canned_copy),
        patch("src.capabilities.drafts.submit_campaign_for_review", return_value={"campaign_id": "cmp-1", "approval_id": "apr-1"}) as mock_submit,
        _NO_EDIT_REQUESTED,
    ):
        result = await draft_campaigns_for_queue("evt-demo-1")

    # One draft, one campaign, one approval — un-surfaced asset skipped
    assert len(result["campaign_ids"]) == 1
    assert len(result["approval_ids"]) == 1
    assert len(result["drafts"]) == 1
    assert mock_submit.call_count == 1

    draft = result["drafts"][0]
    assert draft["asset_id"] == "a1"
    assert draft["headline"] == canned_copy.headline


@pytest.mark.anyio
async def test_draft_campaigns_zero_surfaced_returns_empty():
    """Zero surfaced assets (queue_type=None for all) returns empty result — not an error."""
    from src.capabilities.drafts import draft_campaigns_for_queue
    from tests.conftest import build_valid_event, build_valid_event_narrative, build_valid_asset, build_valid_asset_scores

    event = build_valid_event(event_id="evt-demo-1", event_narrative=build_valid_event_narrative())
    asset_unqueued = build_valid_asset(
        asset_id="a1", event_id="evt-demo-1", status="scored",
        queue_type=None, scores=build_valid_asset_scores(),
    )

    with (
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts.get_assets_for_event", return_value=[asset_unqueued]),
        _NO_EDIT_REQUESTED,
    ):
        result = await draft_campaigns_for_queue("evt-demo-1")

    assert result == {"event_id": "evt-demo-1", "campaign_ids": [], "approval_ids": [], "drafts": []}


@pytest.mark.anyio
async def test_draft_campaigns_precondition_missing_event():
    from src.capabilities.drafts import draft_campaigns_for_queue
    from src.errors import PreconditionError

    with patch("src.capabilities.drafts.get_event", return_value=None):
        with pytest.raises(PreconditionError) as exc_info:
            await draft_campaigns_for_queue("evt-missing")

    assert "event" in exc_info.value.missing


@pytest.mark.anyio
async def test_draft_campaigns_precondition_no_scored_assets():
    from src.capabilities.drafts import draft_campaigns_for_queue
    from src.errors import PreconditionError
    from tests.conftest import build_valid_event, build_valid_event_narrative

    event = build_valid_event(event_id="evt-demo-1", event_narrative=build_valid_event_narrative())

    with (
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts.get_assets_for_event", return_value=[]),
        _NO_EDIT_REQUESTED,
    ):
        with pytest.raises(PreconditionError) as exc_info:
            await draft_campaigns_for_queue("evt-demo-1")

    assert "scores" in exc_info.value.missing


@pytest.mark.anyio
async def test_draft_campaigns_precondition_no_narrative():
    from src.capabilities.drafts import draft_campaigns_for_queue
    from src.errors import PreconditionError
    from tests.conftest import build_valid_event, build_valid_asset, build_valid_asset_scores

    event = build_valid_event(event_id="evt-demo-1", event_narrative=None)
    asset = build_valid_asset(
        asset_id="a1", event_id="evt-demo-1", status="scored",
        scores=build_valid_asset_scores(),
    )

    with (
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts.get_assets_for_event", return_value=[asset]),
        _NO_EDIT_REQUESTED,
    ):
        with pytest.raises(PreconditionError) as exc_info:
            await draft_campaigns_for_queue("evt-demo-1")

    assert "narrative" in exc_info.value.missing


@pytest.mark.anyio
async def test_draft_campaigns_route_mapping_flows_to_campaign():
    """poster route → product_type='poster', platform_target='shopify'."""
    from src.capabilities.drafts import draft_campaigns_for_queue
    from tests.conftest import build_valid_event, build_valid_event_narrative, build_valid_asset, build_valid_asset_scores

    event = build_valid_event(event_id="evt-demo-1", event_narrative=build_valid_event_narrative())
    asset_poster = build_valid_asset(
        asset_id="a1", event_id="evt-demo-1", status="scored",
        queue_type="exploitation", queue_rank=1, queue_rationale="poster candidate",
        product_route="poster", detected_subjects=["Lionel Messi"],
        scores=build_valid_asset_scores(),
    )
    asset_social = build_valid_asset(
        asset_id="a2", event_id="evt-demo-1", status="scored",
        queue_type="discovery", queue_rank=1, queue_rationale="social only",
        product_route="social_only", detected_subjects=[],
        scores=build_valid_asset_scores(),
    )

    canned_copy = build_valid_generated_copy()
    captured_campaigns = []

    async def capture_submit(campaign: Campaign) -> dict:
        captured_campaigns.append(campaign)
        return {"campaign_id": campaign.campaign_id, "approval_id": "apr-x"}

    with (
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts.get_assets_for_event", return_value=[asset_poster, asset_social]),
        patch("src.capabilities.drafts._draft_copy_for_asset", return_value=canned_copy),
        patch("src.capabilities.drafts.submit_campaign_for_review", side_effect=capture_submit),
        _NO_EDIT_REQUESTED,
    ):
        await draft_campaigns_for_queue("evt-demo-1")

    poster_camp = next(c for c in captured_campaigns if c.asset_id == "a1")
    social_camp = next(c for c in captured_campaigns if c.asset_id == "a2")

    assert poster_camp.product_type == "poster"
    assert poster_camp.platform_target == "shopify"
    assert social_camp.product_type is None
    assert social_camp.platform_target == "social"


# ---------------------------------------------------------------------------
# T-6.9: node adapter
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_node_adapter_writes_state():
    """_node_draft_campaigns_for_queue writes campaign_ids/approval_ids/drafts to ctx.state."""
    from src.capabilities import _node_draft_campaigns_for_queue

    fake_result = {
        "event_id": "evt-demo-1",
        "campaign_ids": ["cmp-1"],
        "approval_ids": ["apr-1"],
        "drafts": [{"asset_id": "a1", "headline": "Test"}],
    }

    ctx = MagicMock()
    ctx.state = {"event_id": "evt-demo-1"}

    with patch("src.capabilities.draft_campaigns_for_queue", return_value=fake_result):
        await _node_draft_campaigns_for_queue(ctx)

    assert ctx.state["campaign_ids"] == ["cmp-1"]
    assert ctx.state["approval_ids"] == ["apr-1"]
    assert ctx.state["drafts"] == [{"asset_id": "a1", "headline": "Test"}]


def test_draft_campaigns_for_queue_node_name():
    from src.capabilities import draft_campaigns_for_queue_node
    assert draft_campaigns_for_queue_node.name == "draft_campaigns_for_queue"
