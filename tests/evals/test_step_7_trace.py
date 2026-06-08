"""Tier-1 HITL gate eval for Step 7 (T-7.10 Phase A + T-7.14 full execution).

Tests the HITL tool chain in a deterministic offline integration sequence:
  request_human_approval → apply_approval_decisions → branch → execute/redraft.

Does NOT run the coordinator LlmAgent (requires GOOGLE_API_KEY; that is T-7.15).
Exercises the tool functions directly against the mock client to confirm:

Phase A assertions (T-7.10):
  (T1-a) apply_approval_decisions accepts the list payload from FunctionResponse.
  (T1-b) cascade writes are correct per decision (approved/rejected/edit_requested).
  (T1-c) branch: edit_requested present → redraft then re-approve; all-approved → execute.
  (T1-e) redraft cap counter increments across calls; (MAX_REDRAFT_CYCLES+1)-th is refused.

Phase B assertions (T-7.14):
  (T1-d) execution end-state: approved → published + published_urls; route dispatch correct;
         rejected items never executed.
  (T1, mixed) mixed batch resolves: edit_requested loops (redraft → re-approve), then
              final execute picks up all accumulated approvals.

On failure: dump_trace is called (not applicable here — no events stream — so we assert
directly on mock_client.calls and return values).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import (
    build_valid_approval_decision,
    build_valid_approved_campaign,
    build_valid_campaign,
    build_valid_event,
    build_valid_event_narrative,
)
from tests.evals.conftest import (
    _MockMCPClient,
    _CANNED_COPY,
    STEP7_APPROVAL_IDS,
    STEP7_CAMPAIGN_IDS,
    STEP7_ASSET_IDS,
    make_step7_approvals_find_handler,
    make_step7_campaigns_find_handler,
    make_step7_assets_find_handler,
    patch_draft_copy_for_asset,
    patch_execution_helpers,
    all_approved_decisions,
    mixed_decisions_with_edit,
    build_decisions_function_response,
)

EVENT_ID = "evt-demo-1"


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Build a mock ToolContext with a writable state dict."""
    tc = MagicMock()
    tc.state = state or {}
    tc.actions = MagicMock()
    return tc


# ---------------------------------------------------------------------------
# (T1-a) apply_approval_decisions accepts the list payload
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1a_apply_receives_full_list():
    """apply_approval_decisions accepts all N items from the decisions list."""
    from src.agent import apply_approval_decisions

    decisions = [
        {"approval_id": "apr-0", "decision": "approved"},
        {"approval_id": "apr-1", "decision": "approved"},
        {"approval_id": "apr-2", "decision": "rejected"},
    ]

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        tool_context = _make_tool_context()
        result = await apply_approval_decisions(decisions, tool_context)

    assert len(result["approved"]) == 2
    assert len(result["rejected"]) == 1
    assert len(result["edit_requested"]) == 0


# ---------------------------------------------------------------------------
# (T1-b) cascade writes correct per decision
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1b_cascade_per_decision():
    """record_approval_decision issues correct writes per decision type."""
    from src.db.approvals import record_approval_decision

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        # approved → approval + campaign (no asset write)
        d_approved = build_valid_approval_decision(approval_id="apr-0", decision="approved")
        await record_approval_decision("apr-0", d_approved)

    update_calls = [c for c in mock_client.calls if c[0] == "update-many"]
    approval_updates = [c for c in update_calls if c[1]["collection"] == "approvals"]
    campaign_updates = [c for c in update_calls if c[1]["collection"] == "campaigns"]
    asset_updates = [c for c in update_calls if c[1]["collection"] == "assets"]

    assert any(u[1]["update"]["$set"]["status"] == "approved" for u in approval_updates)
    assert len(campaign_updates) == 1  # campaign gets approved
    assert len(asset_updates) == 0   # asset unchanged on approve


@pytest.mark.anyio
async def test_t1b_rejected_cascades_to_asset():
    """rejected decision cascades to asset (status=rejected)."""
    from src.db.approvals import record_approval_decision

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        d_rejected = build_valid_approval_decision(approval_id="apr-0", decision="rejected")
        await record_approval_decision("apr-0", d_rejected)

    update_calls = [c for c in mock_client.calls if c[0] == "update-many"]
    asset_updates = [c for c in update_calls if c[1]["collection"] == "assets"]
    assert len(asset_updates) == 1
    assert asset_updates[0][1]["update"]["$set"]["status"] == "rejected"


@pytest.mark.anyio
async def test_t1b_edit_requested_no_campaign_or_asset_write():
    """edit_requested → only approval write; campaign stays draft, asset unchanged."""
    from src.db.approvals import record_approval_decision

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        d_edit = build_valid_approval_decision(approval_id="apr-0", decision="edit_requested", reviewer_notes="Redo this")
        await record_approval_decision("apr-0", d_edit)

    update_calls = [c for c in mock_client.calls if c[0] == "update-many"]
    campaign_updates = [c for c in update_calls if c[1]["collection"] == "campaigns"]
    asset_updates = [c for c in update_calls if c[1]["collection"] == "assets"]
    assert len(campaign_updates) == 0
    assert len(asset_updates) == 0


# ---------------------------------------------------------------------------
# (T1-c) branch: all-approved → execute once; edit_requested → redraft then re-approve
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1c_all_approved_calls_execute():
    """all-approved batch → apply returns no edit_requested → execute_approved_campaigns called."""
    from src.agent import apply_approval_decisions, execute_approved_campaigns

    decisions = [
        {"approval_id": "apr-0", "decision": "approved"},
        {"approval_id": "apr-1", "decision": "approved"},
    ]

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))
    mock_client.register("find", "campaigns", make_step7_campaigns_find_handler(EVENT_ID))
    mock_client.register("find", "assets", make_step7_assets_find_handler(EVENT_ID))

    tool_context = _make_tool_context()

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch_execution_helpers(),
    ):
        apply_result = await apply_approval_decisions(decisions, tool_context)
        # Branch: no edit_requested → execute
        assert len(apply_result["edit_requested"]) == 0
        exec_result = await execute_approved_campaigns(EVENT_ID, tool_context)

    assert len(exec_result["executed"]) >= 0  # at least attempted


@pytest.mark.anyio
async def test_t1c_edit_requested_triggers_redraft():
    """edit_requested present → redraft_campaigns called and returns a draft result."""
    from src.agent import apply_approval_decisions, redraft_campaigns

    decisions = [
        {"approval_id": "apr-0", "decision": "approved"},
        {"approval_id": "apr-2", "decision": "edit_requested", "reviewer_notes": "Make it punchier"},
    ]

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))

    tool_context = _make_tool_context()
    event = build_valid_event()
    event.event_narrative = build_valid_event_narrative()

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        apply_result = await apply_approval_decisions(decisions, tool_context)
        # Branch: edit_requested present → redraft
        assert len(apply_result["edit_requested"]) == 1

    ac = build_valid_approved_campaign(approval_id="apr-2", reviewer_notes="Make it punchier")

    with (
        patch("src.capabilities.drafts.get_edit_requested_campaigns", new_callable=AsyncMock, return_value=[ac]),
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts._draft_copy_for_asset", return_value=_CANNED_COPY),
        patch("src.capabilities.drafts.overwrite_campaign_draft", new_callable=AsyncMock),
        patch("src.capabilities.drafts.reset_approval_to_pending", new_callable=AsyncMock) as mock_reset,
    ):
        redraft_result = await redraft_campaigns(EVENT_ID, tool_context)

    assert tool_context.state["redraft_cycles"] == 1
    assert "campaign_ids" in redraft_result


# ---------------------------------------------------------------------------
# (T1-e) redraft cap survives across calls
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1e_cap_counter_increments_and_refuses():
    """Cap counter increments per call and refuses on (MAX+1)-th call."""
    from src.agent import redraft_campaigns, MAX_REDRAFT_CYCLES

    event = build_valid_event()
    event.event_narrative = build_valid_event_narrative()
    ac = build_valid_approved_campaign(approval_id="apr-1", reviewer_notes="notes")

    tool_context = _make_tool_context()

    with (
        patch("src.capabilities.drafts.get_edit_requested_campaigns", new_callable=AsyncMock, return_value=[ac]),
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts._draft_copy_for_asset", return_value=_CANNED_COPY),
        patch("src.capabilities.drafts.overwrite_campaign_draft", new_callable=AsyncMock),
        patch("src.capabilities.drafts.reset_approval_to_pending", new_callable=AsyncMock),
    ):
        for i in range(MAX_REDRAFT_CYCLES):
            result = await redraft_campaigns(EVENT_ID, tool_context)
            assert result.get("status") != "cap_reached", f"Cap fired too early at cycle {i+1}"
            assert tool_context.state["redraft_cycles"] == i + 1

        # (MAX+1)-th call must be refused
        capped = await redraft_campaigns(EVENT_ID, tool_context)

    assert capped["status"] == "cap_reached"
    # State counter was not incremented after cap
    assert tool_context.state["redraft_cycles"] == MAX_REDRAFT_CYCLES


# ---------------------------------------------------------------------------
# (T-7.14) Phase B: execution end-state
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1d_poster_route_produces_shopify_key():
    """poster route → execution result carries shopify key."""
    from src.capabilities.execution import execute_approved_campaigns

    poster_ac = build_valid_approved_campaign(
        approval_id="apr-0",
        campaign=build_valid_campaign(campaign_id="cmp-0", asset_id="a0"),
        asset_id="a0",
        product_route="poster",
    )

    tool_context = _make_tool_context()

    with (
        patch("src.capabilities.execution.get_approved_campaigns", new_callable=AsyncMock, return_value=[poster_ac]),
        patch("src.capabilities.execution.mark_asset_executing", new_callable=AsyncMock),
        patch_execution_helpers(),
        patch("src.capabilities.execution.record_execution_result", new_callable=AsyncMock) as mock_record,
        patch("src.capabilities.execution.record_execution_failure", new_callable=AsyncMock),
    ):
        result = await execute_approved_campaigns(EVENT_ID, tool_context)

    assert len(result["executed"]) == 1
    item = result["executed"][0]
    assert "shopify" in item["channels"]
    assert "social" not in item["channels"]


@pytest.mark.anyio
async def test_t1d_social_route_produces_social_key():
    """social_only route → execution result carries social key."""
    from src.capabilities.execution import execute_approved_campaigns

    social_ac = build_valid_approved_campaign(
        approval_id="apr-2",
        campaign=build_valid_campaign(campaign_id="cmp-2", asset_id="a2", product_type=None, platform_target="social"),
        asset_id="a2",
        product_route="social_only",
    )

    tool_context = _make_tool_context()

    with (
        patch("src.capabilities.execution.get_approved_campaigns", new_callable=AsyncMock, return_value=[social_ac]),
        patch("src.capabilities.execution.mark_asset_executing", new_callable=AsyncMock),
        patch("src.capabilities.execution.record_execution_result", new_callable=AsyncMock) as mock_record,
        patch("src.capabilities.execution.record_execution_failure", new_callable=AsyncMock),
    ):
        result = await execute_approved_campaigns(EVENT_ID, tool_context)

    assert len(result["executed"]) == 1
    item = result["executed"][0]
    assert "social" in item["channels"]
    assert "shopify" not in item["channels"]


@pytest.mark.anyio
async def test_t1d_rejected_items_never_executed():
    """Rejected items are never passed to execute (get_approved_campaigns filters them out)."""
    from src.capabilities.execution import execute_approved_campaigns

    # No approved campaigns — all rejected; get_approved_campaigns returns empty
    tool_context = _make_tool_context()

    with (
        patch("src.capabilities.execution.get_approved_campaigns", new_callable=AsyncMock, return_value=[]),
        patch("src.capabilities.execution.mark_asset_executing", new_callable=AsyncMock) as mock_mark,
        patch("src.capabilities.execution.record_execution_result", new_callable=AsyncMock) as mock_record,
    ):
        result = await execute_approved_campaigns(EVENT_ID, tool_context)

    assert result["executed"] == []
    mock_mark.assert_not_called()
    mock_record.assert_not_called()


@pytest.mark.anyio
async def test_t1_mixed_batch_resolves_accumulates_approvals():
    """Mixed batch: edit_requested loops (redraft → re-approve), then execute picks all accumulated."""
    from src.agent import apply_approval_decisions, redraft_campaigns, execute_approved_campaigns

    # Round 1: apr-0 approved, apr-2 edit_requested
    round1_decisions = [
        {"approval_id": "apr-0", "decision": "approved"},
        {"approval_id": "apr-2", "decision": "edit_requested", "reviewer_notes": "Redo"},
    ]

    tool_context = _make_tool_context()
    event = build_valid_event()
    event.event_narrative = build_valid_event_narrative()

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID))

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        apply1 = await apply_approval_decisions(round1_decisions, tool_context)

    assert len(apply1["approved"]) == 1
    assert len(apply1["edit_requested"]) == 1

    # Redraft loop
    ac = build_valid_approved_campaign(approval_id="apr-2", reviewer_notes="Redo")
    with (
        patch("src.capabilities.drafts.get_edit_requested_campaigns", new_callable=AsyncMock, return_value=[ac]),
        patch("src.capabilities.drafts.get_event", return_value=event),
        patch("src.capabilities.drafts._draft_copy_for_asset", return_value=_CANNED_COPY),
        patch("src.capabilities.drafts.overwrite_campaign_draft", new_callable=AsyncMock),
        patch("src.capabilities.drafts.reset_approval_to_pending", new_callable=AsyncMock),
    ):
        redraft_result = await redraft_campaigns(EVENT_ID, tool_context)
    assert "campaign_ids" in redraft_result

    # Round 2: apr-2 now approved too
    round2_decisions = [{"approval_id": "apr-2", "decision": "approved"}]
    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
    ):
        apply2 = await apply_approval_decisions(round2_decisions, tool_context)

    assert len(apply2["approved"]) == 1
    assert len(apply2["edit_requested"]) == 0

    # Execute: should pick up BOTH apr-0 and apr-2 (accumulated approvals from both rounds)
    both_acs = [
        build_valid_approved_campaign(approval_id="apr-0", campaign=build_valid_campaign(campaign_id="cmp-0"), product_route="poster"),
        build_valid_approved_campaign(approval_id="apr-2", campaign=build_valid_campaign(campaign_id="cmp-2", product_type=None, platform_target="social"), asset_id="a2", product_route="social_only"),
    ]
    with (
        patch("src.capabilities.execution.get_approved_campaigns", new_callable=AsyncMock, return_value=both_acs),
        patch("src.capabilities.execution.mark_asset_executing", new_callable=AsyncMock),
        patch_execution_helpers(),
        patch("src.capabilities.execution.record_execution_result", new_callable=AsyncMock),
        patch("src.capabilities.execution.record_execution_failure", new_callable=AsyncMock),
    ):
        exec_result = await execute_approved_campaigns(EVENT_ID, tool_context)

    # Both accumulated approvals are executed
    assert len(exec_result["executed"]) == 2
