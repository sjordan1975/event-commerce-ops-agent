"""Tier-1 trace eval for Step 8 — record_outcomes (T-8.9).

Deterministic, mocked — no GOOGLE_API_KEY, no live MongoDB, no external APIs.
Extends the Step-7 direct-tool sequence through record_outcomes.

Asserts:
  (T1-a) after execute_approved_campaigns, record_outcomes writes one performance
         upsert per published asset.
  (T1-b) correct (asset_id, campaign_id, event_id) linkage; channels match product_route;
         metrics=None; metrics_status="pending_sync"; window_days=7.
  (T1-c) idempotency — second call upserts (same filter), does not duplicate keys.
  (T1-d) no-op guard — record_outcomes on an event with no published assets writes
         nothing and returns nothing_to_record.
  (T1-e) honest terminal return — pending_sync=True; no metrics/numbers claimed.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.evals.conftest import (
    _MockMCPClient,
    STEP7_APPROVAL_IDS,
    STEP7_CAMPAIGN_IDS,
    STEP7_ASSET_IDS,
    STEP8_PUBLISHED_AT,
    make_step7_approvals_find_handler,
    make_step8_assets_find_handler,
    make_step8_campaigns_find_handler,
    patch_execution_helpers,
)

EVENT_ID = "evt-demo-1"


def _make_tool_context(state: dict | None = None) -> MagicMock:
    tc = MagicMock()
    tc.state = state or {}
    tc.actions = MagicMock()
    return tc


def _perf_write_calls(mock_client: _MockMCPClient) -> list[tuple]:
    return [c for c in mock_client.calls if c[0] == "update-many" and c[1].get("collection") == "performance"]


# ---------------------------------------------------------------------------
# (T1-a) record_outcomes writes one upsert per published asset after execute
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1a_record_outcomes_called_after_execute_writes_one_per_asset():
    """Execute → record_outcomes writes exactly one performance upsert per published asset."""
    from src.capabilities.execution import execute_approved_campaigns
    from src.capabilities.outcomes import record_outcomes

    mock_client = _MockMCPClient()
    mock_client.register("find", "approvals", make_step7_approvals_find_handler(EVENT_ID, {"apr-0": "approved", "apr-1": "approved", "apr-2": "approved"}))
    mock_client.register("find", "campaigns", make_step8_campaigns_find_handler(EVENT_ID))
    mock_client.register("find", "assets", make_step8_assets_find_handler(EVENT_ID))

    tc = _make_tool_context()

    with (
        patch("src.db.approvals.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
        patch_execution_helpers(),
        patch("src.capabilities.execution.mark_asset_executing", new_callable=AsyncMock),
        patch("src.capabilities.execution.record_execution_result", new_callable=AsyncMock),
        patch("src.capabilities.execution.record_execution_failure", new_callable=AsyncMock),
    ):
        exec_result = await execute_approved_campaigns(EVENT_ID, tc)
        record_result = await record_outcomes(EVENT_ID, tc)

    assert record_result["status"] == "recorded"
    assert record_result["count"] == 3  # one per published asset (ast-0, ast-1, ast-2)
    perf_writes = _perf_write_calls(mock_client)
    assert len(perf_writes) == 3


# ---------------------------------------------------------------------------
# (T1-b) correct linkage, channels, metrics=None, pending_sync, window_days=7
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1b_provenance_doc_linkage_and_shape():
    """Each provenance doc has correct (asset_id, campaign_id, event_id), channels, metrics=None."""
    from src.capabilities.outcomes import record_outcomes

    mock_client = _MockMCPClient()
    mock_client.register("find", "assets", make_step8_assets_find_handler(EVENT_ID))
    mock_client.register("find", "campaigns", make_step8_campaigns_find_handler(EVENT_ID))

    tc = _make_tool_context()

    with (
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
    ):
        result = await record_outcomes(EVENT_ID, tc)

    perf_writes = _perf_write_calls(mock_client)
    assert len(perf_writes) == 3

    payloads_by_asset = {c[1]["update"]["$set"]["asset_id"]: c[1]["update"]["$set"] for c in perf_writes}

    # ast-0: poster → shopify
    p0 = payloads_by_asset["ast-0"]
    assert p0["campaign_id"] == "cmp-0"
    assert p0["event_id"] == EVENT_ID
    assert p0["channels"] == ["shopify"]
    assert p0["metrics"] is None
    assert p0["metrics_status"] == "pending_sync"
    assert p0["window_days"] == 7
    # window_start should be the executed_at from the campaign fixture
    assert p0["window_start"] == STEP8_PUBLISHED_AT

    # ast-1: tshirt → shopify
    p1 = payloads_by_asset["ast-1"]
    assert p1["channels"] == ["shopify"]
    assert p1["metrics"] is None
    assert p1["metrics_status"] == "pending_sync"

    # ast-2: social_only → social
    p2 = payloads_by_asset["ast-2"]
    assert p2["channels"] == ["social"]
    assert p2["metrics"] is None
    assert p2["metrics_status"] == "pending_sync"


# ---------------------------------------------------------------------------
# (T1-c) idempotency — second call upserts same filter, does not duplicate
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1c_idempotency_second_call_same_filter():
    """Second record_outcomes call issues the same filter+upsert — no new distinct filter."""
    from src.capabilities.outcomes import record_outcomes

    mock_client = _MockMCPClient()
    mock_client.register("find", "assets", make_step8_assets_find_handler(EVENT_ID))
    mock_client.register("find", "campaigns", make_step8_campaigns_find_handler(EVENT_ID))

    tc = _make_tool_context()

    with (
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
    ):
        await record_outcomes(EVENT_ID, tc)
        await record_outcomes(EVENT_ID, tc)

    perf_writes = _perf_write_calls(mock_client)
    # 3 assets × 2 calls = 6 writes total (each is an upsert on the same filter)
    assert len(perf_writes) == 6

    # Each pair for the same asset must use the same filter
    filters_by_asset: dict[str, list[dict]] = {}
    for c in perf_writes:
        filt = c[1]["filter"]
        aid = filt["asset_id"]
        filters_by_asset.setdefault(aid, []).append(filt)

    for aid, filters in filters_by_asset.items():
        assert filters[0] == filters[1], f"filter changed on second call for {aid}"
        assert all(c[1].get("upsert") is True for c in perf_writes if c[1]["filter"]["asset_id"] == aid)


# ---------------------------------------------------------------------------
# (T1-d) no-op guard — event with no published assets writes nothing
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1d_noop_guard_no_published_assets():
    """record_outcomes on an event with no published assets writes nothing."""
    from src.capabilities.outcomes import record_outcomes

    mock_client = _MockMCPClient()
    # Register a handler that returns empty for published assets
    mock_client.register("find", "assets", lambda args: [])

    tc = _make_tool_context()

    with (
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
    ):
        result = await record_outcomes(EVENT_ID, tc)

    assert result["status"] == "nothing_to_record"
    assert result["event_id"] == EVENT_ID
    assert len(_perf_write_calls(mock_client)) == 0


# ---------------------------------------------------------------------------
# (T1-e) honest terminal return — pending_sync=True, no metrics numbers
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_t1e_honest_terminal_return():
    """record_outcomes return dict carries pending_sync=True and no metrics values."""
    from src.capabilities.outcomes import record_outcomes

    mock_client = _MockMCPClient()
    mock_client.register("find", "assets", make_step8_assets_find_handler(EVENT_ID))
    mock_client.register("find", "campaigns", make_step8_campaigns_find_handler(EVENT_ID))

    tc = _make_tool_context()

    with (
        patch("src.db.assets.get_client", return_value=mock_client),
        patch("src.db.campaigns.get_client", return_value=mock_client),
        patch("src.db.performance.get_client", return_value=mock_client),
    ):
        result = await record_outcomes(EVENT_ID, tc)

    assert result["status"] == "recorded"
    assert result["pending_sync"] is True

    # None of the records should carry metrics — that would be fabrication
    for record in result["records"]:
        assert "metrics" not in record or record.get("metrics") is None

    # The written docs also have no metrics
    for c in _perf_write_calls(mock_client):
        payload = c[1]["update"]["$set"]
        assert payload["metrics"] is None
        assert payload["metrics_status"] == "pending_sync"
