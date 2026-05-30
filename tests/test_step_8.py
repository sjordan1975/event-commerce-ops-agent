"""Unit tests for Step 8 — record_outcomes (capability 9).

Covers:
  - channels_for_route mapping
  - record_performance idempotent upsert
  - aggregate_performance_for_events spine fix (pending-neutral regression)
  - record_outcomes capability (no-op guard, linkage, window anchor)
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mcp_ok() -> dict:
    return {"content": [{"type": "text", "text": "ok"}]}


def _make_mcp_envelope(docs: list[dict]) -> dict:
    import json
    if not docs:
        return {"content": [{"type": "text", "text": "Query resulted in 0 documents."}]}
    uid = "mock-uuid-test"
    data = (
        f"Query resulted in {len(docs)} documents.\n\n"
        f"<untrusted-user-data-{uid}>\n"
        f"{json.dumps(docs)}\n"
        f"</untrusted-user-data-{uid}>\n"
        "Use the information above to respond."
    )
    return {
        "content": [
            {"type": "text", "text": f"Query resulted in {len(docs)} documents."},
            {"type": "text", "text": data},
        ]
    }


class _WriteMockClient:
    """Records all calls; read calls return canned data from the dispatch table."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._reads: dict[tuple, list[dict] | dict] = {}

    def register_read(self, tool: str, collection: str, result: list[dict] | dict) -> None:
        self._reads[(tool, collection)] = result

    async def call(self, tool_name: str, args: dict) -> dict:
        self.calls.append((tool_name, args))
        key = (tool_name, args.get("collection", ""))
        if key in self._reads:
            val = self._reads[key]
            if callable(val):
                return _make_mcp_envelope(val(args))
            if isinstance(val, list):
                return _make_mcp_envelope(val)
            return val
        return _make_mcp_ok()

    def write_calls(self, tool: str | None = None, collection: str | None = None) -> list[tuple[str, dict]]:
        return [
            c for c in self.calls
            if (tool is None or c[0] == tool)
            and (collection is None or c[1].get("collection") == collection)
        ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# T-8.3: channels_for_route
# ---------------------------------------------------------------------------

def test_channels_poster():
    from src.db.performance import channels_for_route
    assert channels_for_route("poster") == ["shopify", "printful"]


def test_channels_tshirt():
    from src.db.performance import channels_for_route
    assert channels_for_route("tshirt") == ["shopify", "printful"]


def test_channels_social_only():
    from src.db.performance import channels_for_route
    assert channels_for_route("social_only") == ["social"]


def test_channels_none():
    from src.db.performance import channels_for_route
    assert channels_for_route(None) == ["social"]


def test_channels_unknown():
    from src.db.performance import channels_for_route
    assert channels_for_route("unknown_route") == ["social"]


# ---------------------------------------------------------------------------
# T-8.3: record_performance upsert (write-recording)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_performance_writes_expected_payload():
    """record_performance issues update-many with $set payload + upsert=True."""
    from src.db.performance import record_performance

    mock = _WriteMockClient()
    with patch("src.db.performance.get_client", return_value=mock):
        await record_performance(
            asset_id="ast-0",
            campaign_id="cmp-0",
            event_id="evt-demo-1",
            product_route="poster",
            window_start="2026-06-01T21:00:00Z",
            metrics=None,
        )

    writes = mock.write_calls("update-many", "performance")
    assert len(writes) == 1
    call = writes[0][1]
    assert call["filter"] == {"asset_id": "ast-0", "event_id": "evt-demo-1"}
    assert call.get("upsert") is True
    payload = call["update"]["$set"]
    assert payload["asset_id"] == "ast-0"
    assert payload["campaign_id"] == "cmp-0"
    assert payload["event_id"] == "evt-demo-1"
    assert payload["channels"] == ["shopify", "printful"]
    assert payload["metrics"] is None
    assert payload["metrics_status"] == "pending_sync"
    assert payload["window_days"] == 7
    assert payload["window_start"] == "2026-06-01T21:00:00Z"
    assert "recorded_at" in payload


@pytest.mark.anyio
async def test_record_performance_metrics_none_gives_pending_sync():
    from src.db.performance import record_performance

    mock = _WriteMockClient()
    with patch("src.db.performance.get_client", return_value=mock):
        await record_performance(
            asset_id="ast-1", campaign_id="cmp-1", event_id="evt-demo-1",
            product_route="social_only", window_start=None, metrics=None,
        )

    writes = mock.write_calls("update-many", "performance")
    payload = writes[0][1]["update"]["$set"]
    assert payload["metrics_status"] == "pending_sync"
    assert payload["channels"] == ["social"]


@pytest.mark.anyio
async def test_record_performance_channel_breakdown_by_route():
    """Each route maps to correct channels in the persisted doc."""
    from src.db.performance import record_performance

    for route, expected_channels in [
        ("poster", ["shopify", "printful"]),
        ("tshirt", ["shopify", "printful"]),
        ("social_only", ["social"]),
        (None, ["social"]),
    ]:
        mock = _WriteMockClient()
        with patch("src.db.performance.get_client", return_value=mock):
            await record_performance(
                asset_id=f"ast-x", campaign_id="cmp-x", event_id="evt-x",
                product_route=route, window_start=None, metrics=None,
            )
        writes = mock.write_calls("update-many", "performance")
        payload = writes[0][1]["update"]["$set"]
        assert payload["channels"] == expected_channels, f"route={route}"


@pytest.mark.anyio
async def test_record_performance_idempotency_same_filter_upsert():
    """Two calls for (asset_id, event_id) both use the same filter + upsert=True."""
    from src.db.performance import record_performance

    mock = _WriteMockClient()
    with patch("src.db.performance.get_client", return_value=mock):
        await record_performance("ast-0", "cmp-0", "evt-1", "poster", None)
        await record_performance("ast-0", "cmp-0", "evt-1", "poster", None)

    writes = mock.write_calls("update-many", "performance")
    assert len(writes) == 2
    for call in writes:
        assert call[1]["filter"] == {"asset_id": "ast-0", "event_id": "evt-1"}
        assert call[1].get("upsert") is True


@pytest.mark.anyio
async def test_record_performance_deterministic_performance_id():
    """performance_id is stable across two calls for the same (asset_id, event_id)."""
    from src.db.performance import record_performance

    mock = _WriteMockClient()
    with patch("src.db.performance.get_client", return_value=mock):
        await record_performance("ast-0", "cmp-0", "evt-1", "poster", None)
        await record_performance("ast-0", "cmp-0", "evt-1", "poster", None)

    writes = mock.write_calls("update-many", "performance")
    id1 = writes[0][1]["update"]["$set"]["performance_id"]
    id2 = writes[1][1]["update"]["$set"]["performance_id"]
    assert id1 == id2


@pytest.mark.anyio
async def test_record_performance_window_start_carried_through():
    """window_start is propagated unchanged when provided."""
    from src.db.performance import record_performance

    mock = _WriteMockClient()
    ws = "2026-06-01T21:30:00Z"
    with patch("src.db.performance.get_client", return_value=mock):
        await record_performance("ast-0", "cmp-0", "evt-1", "poster", ws)

    writes = mock.write_calls("update-many", "performance")
    assert writes[0][1]["update"]["$set"]["window_start"] == ws


# ---------------------------------------------------------------------------
# T-8.4: Spine fix — aggregate_performance_for_events excludes pending docs
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_baseline_pending_neutral():
    """aggregate_performance_for_events returns identical output with/without pending docs.

    Validates that the leading $match {metrics_status: {$ne: "pending_sync"}} in
    the pipeline excludes pending docs (and keeps docs with no metrics_status field).
    The handler applies the pipeline's $match stage to raw seeded docs so the test
    is sensitive to the actual pipeline shape — removing the $match causes failure.
    """
    from src.db.performance import aggregate_performance_for_events

    # Measured doc (no metrics_status — legacy/seeded shape; must be kept by $ne filter)
    measured_doc = {
        "asset_id": "ast-hist-1",
        "event_id": "evt-past-1",
        "metrics": {"shopify": {"orders": 50}, "social": {"impressions": 3000}},
        # No metrics_status field — backward-compat; $ne filter keeps these
    }
    # Pending provenance doc written by record_performance (must be excluded)
    pending_doc = {
        "asset_id": "ast-curr-1",
        "event_id": "evt-past-1",
        "metrics": None,
        "metrics_status": "pending_sync",
    }
    # Asset docs for $lookup
    asset_docs = [
        {"asset_id": "ast-hist-1", "product_route": "poster"},
        {"asset_id": "ast-curr-1", "product_route": "tshirt"},
    ]

    async def _run_with_docs(perf_docs: list[dict]) -> dict:
        """Run aggregate against a handler that applies the pipeline's first $match."""
        import json, re

        class _PipelineAwareMock:
            async def call(self, tool_name: str, args: dict) -> dict:
                if tool_name == "aggregate" and args.get("collection") == "performance":
                    pipeline = args.get("pipeline", [])
                    docs = list(perf_docs)
                    # Apply leading $match stages so the test is sensitive to the production pipeline
                    for stage in pipeline:
                        if "$match" in stage:
                            match = stage["$match"]
                            filtered = []
                            for d in docs:
                                include = True
                                for k, v in match.items():
                                    if isinstance(v, dict) and "$ne" in v:
                                        # $ne: keep docs where field != value OR field absent
                                        if d.get(k) == v["$ne"]:
                                            include = False
                                            break
                                    elif isinstance(v, dict) and "$in" in v:
                                        if d.get(k) not in v["$in"]:
                                            include = False
                                            break
                                    else:
                                        if d.get(k) != v:
                                            include = False
                                            break
                                if include:
                                    filtered.append(d)
                            docs = filtered
                        elif "$lookup" in stage:
                            # Attach asset product_route via $lookup
                            lk = stage["$lookup"]
                            for d in docs:
                                matches = [a for a in asset_docs if a[lk["foreignField"]] == d[lk["localField"]]]
                                d[lk["as"]] = matches
                        elif "$unwind" in stage:
                            field = stage["$unwind"].lstrip("$")
                            new_docs = []
                            for d in docs:
                                arr = d.get(field, [])
                                for item in arr:
                                    new_d = dict(d)
                                    new_d[field] = item
                                    new_docs.append(new_d)
                            docs = new_docs
                        elif "$group" in stage:
                            from collections import defaultdict
                            groups: dict = defaultdict(lambda: {"total_orders": 0, "total_impressions": 0, "count": 0})
                            grp_spec = stage["$group"]
                            for d in docs:
                                _id_spec = grp_spec["_id"]
                                if isinstance(_id_spec, str) and _id_spec.startswith("$"):
                                    field_path = _id_spec.lstrip("$").split(".")
                                    val = d
                                    for part in field_path:
                                        if isinstance(val, dict):
                                            val = val.get(part)
                                        else:
                                            val = None
                                            break
                                    gid = val
                                else:
                                    gid = _id_spec
                                g = groups[gid]
                                metrics = d.get("metrics") or {}
                                shopify = metrics.get("shopify") or {}
                                social = metrics.get("social") or {}
                                g["total_orders"] += shopify.get("orders", 0)
                                g["total_impressions"] += social.get("impressions", 0)
                                g["count"] += 1
                            docs = [{"_id": k, **v} for k, v in groups.items()]
                        elif "$sort" in stage:
                            sort_spec = stage["$sort"]
                            field, direction = next(iter(sort_spec.items()))
                            docs = sorted(docs, key=lambda d: d.get(field, 0), reverse=(direction == -1))
                    # Return envelope
                    if not docs:
                        return {"content": [{"type": "text", "text": "Query resulted in 0 documents."}]}
                    uid = "mock-uuid"
                    data = (
                        f"Query resulted in {len(docs)} documents.\n\n"
                        f"<untrusted-user-data-{uid}>\n"
                        f"{json.dumps(docs)}\n"
                        f"</untrusted-user-data-{uid}>\n"
                        "Use the information above to respond."
                    )
                    return {"content": [
                        {"type": "text", "text": f"Query resulted in {len(docs)} documents."},
                        {"type": "text", "text": data},
                    ]}
                return {"content": [{"type": "text", "text": "ok"}]}

        with patch("src.db.performance.get_client", return_value=_PipelineAwareMock()):
            return await aggregate_performance_for_events(["evt-past-1"])

    # Measured only
    result_measured_only = await _run_with_docs([measured_doc])
    # Measured + pending
    result_with_pending = await _run_with_docs([measured_doc, pending_doc])

    assert result_measured_only["top_product_route"] == result_with_pending["top_product_route"], (
        "Pending doc changed top_product_route — spine fix may be missing"
    )
    assert result_measured_only["total_orders"] == result_with_pending["total_orders"], (
        "Pending doc changed total_orders — spine fix may be missing"
    )
    assert result_measured_only["asset_count"] == result_with_pending["asset_count"], (
        "Pending doc changed asset_count — spine fix may be missing"
    )


# ---------------------------------------------------------------------------
# T-8.5: record_outcomes capability
# ---------------------------------------------------------------------------

def _make_published_asset(asset_id: str, event_id: str, campaign_id: str, product_route: str | None) -> dict:
    return {
        "asset_id": asset_id,
        "event_id": event_id,
        "content_url": f"gs://bucket/{asset_id}.jpg",
        "status": "published",
        "upload_date": _now(),
        "product_route": product_route,
        "queue_type": "exploitation",
        "queue_rank": 1,
        "queue_rationale": "test",
        "embedding": None,
        "scores": None,
        "detected_subjects": [],
        "campaign_id": campaign_id,
        "similar_assets": None,
        "published_urls": {"shopify": "https://demo.myshopify.com/products/x"},
    }


def _make_executed_campaign(campaign_id: str, asset_id: str, event_id: str, product_route: str | None, executed_at: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "asset_id": asset_id,
        "event_id": event_id,
        "product_type": "poster" if product_route == "poster" else None,
        "generated_copy": {
            "headline": "Headline",
            "caption": "Caption",
            "hashtags": ["#Test"],
        },
        "platform_target": "shopify",
        "timing_recommendation": "2026-06-01T23:00:00Z",
        "status": "executed",
        "created_at": _now(),
        "execution": {"executed_at": executed_at, "shopify": {"product_id": "gid://1"}},
    }


EVENT_ID = "evt-demo-1"
EXECUTED_AT = "2026-06-01T21:05:00Z"


@pytest.mark.anyio
async def test_record_outcomes_one_doc_per_published_asset():
    """record_outcomes writes one upsert per published asset."""
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    published = [_make_published_asset("ast-0", EVENT_ID, "cmp-0", "poster")]
    campaigns = [_make_executed_campaign("cmp-0", "ast-0", EVENT_ID, "poster", EXECUTED_AT)]

    mock = _WriteMockClient()
    mock.register_read("find", "assets", published)
    mock.register_read("find", "campaigns", campaigns)
    tc = MagicMock(); tc.state = {}

    with (
        patch("src.db.assets.get_client", return_value=mock),
        patch("src.db.campaigns.get_client", return_value=mock),
        patch("src.db.performance.get_client", return_value=mock),
    ):
        result = await record_outcomes(EVENT_ID, tc)

    perf_writes = mock.write_calls("update-many", "performance")
    assert len(perf_writes) == 1
    assert result["status"] == "recorded"
    assert result["count"] == 1
    assert result["pending_sync"] is True


@pytest.mark.anyio
async def test_record_outcomes_correct_linkage():
    """Correct (asset_id, campaign_id, event_id) linkage in the provenance doc."""
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    published = [_make_published_asset("ast-0", EVENT_ID, "cmp-0", "poster")]
    campaigns = [_make_executed_campaign("cmp-0", "ast-0", EVENT_ID, "poster", EXECUTED_AT)]

    mock = _WriteMockClient()
    mock.register_read("find", "assets", published)
    mock.register_read("find", "campaigns", campaigns)
    tc = MagicMock(); tc.state = {}

    with (
        patch("src.db.assets.get_client", return_value=mock),
        patch("src.db.campaigns.get_client", return_value=mock),
        patch("src.db.performance.get_client", return_value=mock),
    ):
        await record_outcomes(EVENT_ID, tc)

    writes = mock.write_calls("update-many", "performance")
    payload = writes[0][1]["update"]["$set"]
    assert payload["asset_id"] == "ast-0"
    assert payload["campaign_id"] == "cmp-0"
    assert payload["event_id"] == EVENT_ID


@pytest.mark.anyio
async def test_record_outcomes_channels_by_route():
    """channels in provenance doc match product_route."""
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    cases = [
        ("ast-0", "cmp-0", "poster", ["shopify", "printful"]),
        ("ast-1", "cmp-1", "social_only", ["social"]),
    ]

    for asset_id, campaign_id, route, expected_channels in cases:
        published = [_make_published_asset(asset_id, EVENT_ID, campaign_id, route)]
        campaigns = [_make_executed_campaign(campaign_id, asset_id, EVENT_ID, route, EXECUTED_AT)]

        mock = _WriteMockClient()
        mock.register_read("find", "assets", published)
        mock.register_read("find", "campaigns", campaigns)
        tc = MagicMock(); tc.state = {}

        with (
            patch("src.db.assets.get_client", return_value=mock),
            patch("src.db.campaigns.get_client", return_value=mock),
            patch("src.db.performance.get_client", return_value=mock),
        ):
            await record_outcomes(EVENT_ID, tc)

        writes = mock.write_calls("update-many", "performance")
        assert writes[0][1]["update"]["$set"]["channels"] == expected_channels, f"route={route}"


@pytest.mark.anyio
async def test_record_outcomes_metrics_none_and_pending_status():
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    published = [_make_published_asset("ast-0", EVENT_ID, "cmp-0", "poster")]
    campaigns = [_make_executed_campaign("cmp-0", "ast-0", EVENT_ID, "poster", EXECUTED_AT)]

    mock = _WriteMockClient()
    mock.register_read("find", "assets", published)
    mock.register_read("find", "campaigns", campaigns)
    tc = MagicMock(); tc.state = {}

    with (
        patch("src.db.assets.get_client", return_value=mock),
        patch("src.db.campaigns.get_client", return_value=mock),
        patch("src.db.performance.get_client", return_value=mock),
    ):
        await record_outcomes(EVENT_ID, tc)

    writes = mock.write_calls("update-many", "performance")
    payload = writes[0][1]["update"]["$set"]
    assert payload["metrics"] is None
    assert payload["metrics_status"] == "pending_sync"
    assert payload["window_days"] == 7


@pytest.mark.anyio
async def test_record_outcomes_window_start_from_execution():
    """window_start is pulled from campaign.execution.executed_at."""
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    published = [_make_published_asset("ast-0", EVENT_ID, "cmp-0", "poster")]
    campaigns = [_make_executed_campaign("cmp-0", "ast-0", EVENT_ID, "poster", EXECUTED_AT)]

    mock = _WriteMockClient()
    mock.register_read("find", "assets", published)
    mock.register_read("find", "campaigns", campaigns)
    tc = MagicMock(); tc.state = {}

    with (
        patch("src.db.assets.get_client", return_value=mock),
        patch("src.db.campaigns.get_client", return_value=mock),
        patch("src.db.performance.get_client", return_value=mock),
    ):
        await record_outcomes(EVENT_ID, tc)

    writes = mock.write_calls("update-many", "performance")
    assert writes[0][1]["update"]["$set"]["window_start"] == EXECUTED_AT


@pytest.mark.anyio
async def test_record_outcomes_noop_guard_no_published_assets():
    """record_outcomes returns nothing_to_record and writes nothing when no published assets."""
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    mock = _WriteMockClient()
    mock.register_read("find", "assets", [])  # no published assets
    tc = MagicMock(); tc.state = {}

    with (
        patch("src.db.assets.get_client", return_value=mock),
        patch("src.db.campaigns.get_client", return_value=mock),
        patch("src.db.performance.get_client", return_value=mock),
    ):
        result = await record_outcomes(EVENT_ID, tc)

    perf_writes = mock.write_calls("update-many", "performance")
    assert result["status"] == "nothing_to_record"
    assert result["event_id"] == EVENT_ID
    assert len(perf_writes) == 0


@pytest.mark.anyio
async def test_record_outcomes_idempotency_same_filter():
    """Second call upserts same filter — does not produce a second distinct filter key."""
    from src.capabilities.outcomes import record_outcomes
    from unittest.mock import MagicMock

    published = [_make_published_asset("ast-0", EVENT_ID, "cmp-0", "poster")]
    campaigns = [_make_executed_campaign("cmp-0", "ast-0", EVENT_ID, "poster", EXECUTED_AT)]

    mock = _WriteMockClient()
    mock.register_read("find", "assets", published)
    mock.register_read("find", "campaigns", campaigns)
    tc = MagicMock(); tc.state = {}

    with (
        patch("src.db.assets.get_client", return_value=mock),
        patch("src.db.campaigns.get_client", return_value=mock),
        patch("src.db.performance.get_client", return_value=mock),
    ):
        await record_outcomes(EVENT_ID, tc)
        await record_outcomes(EVENT_ID, tc)

    perf_writes = mock.write_calls("update-many", "performance")
    # Both calls use the same filter (idempotent upsert — same key, not two distinct inserts)
    filters = [c[1]["filter"] for c in perf_writes]
    assert filters[0] == filters[1]
    assert all(c[1].get("upsert") is True for c in perf_writes)
