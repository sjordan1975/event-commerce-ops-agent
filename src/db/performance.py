"""Internal MongoDB wrapper for the performance collection."""

import hashlib
from datetime import datetime, timezone

from src.db import _parse_docs_response, get_client
from src.models import Performance, PerformanceMetrics

_EMPTY_BASELINE = {
    "past_event_count": 0,
    "top_product_route": None,
    "total_orders": 0,
    "total_impressions": 0,
    "asset_count": 0,
}


async def aggregate_performance_for_events(event_ids: list[str]) -> dict:
    """Aggregate historical performance metrics for a cohort of event_ids.

    Joins performance docs to assets via $lookup to surface product_route.
    Returns {"past_event_count", "top_product_route", "total_orders",
    "total_impressions", "asset_count"}. past_event_count equals len(event_ids)
    regardless of how many events have performance records.
    """
    if not event_ids:
        return dict(_EMPTY_BASELINE)

    pipeline = [
        # Exclude pending provenance docs so the Step-2 baseline stays measured-only.
        # $ne (not $eq "synced") preserves legacy docs with no metrics_status field.
        {"$match": {"metrics_status": {"$ne": "pending_sync"}}},
        {"$match": {"event_id": {"$in": event_ids}}},
        {"$match": {"event_id": {"$in": event_ids}}},
        {
            "$lookup": {
                "from": "assets",
                "localField": "asset_id",
                "foreignField": "asset_id",
                "as": "asset",
            }
        },
        {"$unwind": "$asset"},
        {
            "$group": {
                "_id": "$asset.product_route",
                "total_orders": {"$sum": "$metrics.shopify.orders"},
                "total_impressions": {"$sum": "$metrics.social.impressions"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"total_orders": -1}},
    ]

    envelope = await get_client().call("aggregate", {
        "database": "event_commerce",
        "collection": "performance",
        "pipeline": pipeline,
    })
    docs = _parse_docs_response(envelope)

    if not docs:
        return {**_EMPTY_BASELINE, "past_event_count": len(event_ids)}

    top_product_route = docs[0]["_id"]
    total_orders = sum(d.get("total_orders", 0) for d in docs)
    total_impressions = sum(d.get("total_impressions", 0) for d in docs)
    asset_count = sum(d.get("count", 0) for d in docs)

    return {
        "past_event_count": len(event_ids),
        "top_product_route": top_product_route,
        "total_orders": total_orders,
        "total_impressions": total_impressions,
        "asset_count": asset_count,
    }


def channels_for_route(product_route: str | None) -> list[str]:
    """Map product_route to channel list (mirrors Step 7 execution dispatch, D-030)."""
    if product_route in ("poster", "tshirt"):
        return ["shopify"]
    return ["social"]


async def record_performance(
    asset_id: str,
    campaign_id: str,
    event_id: str,
    product_route: str | None,
    window_start: str | None,
    metrics: PerformanceMetrics | None = None,
) -> None:
    """Upsert one provenance performance doc keyed by (asset_id, event_id).

    performance_id is deterministic from (asset_id, event_id) so re-runs
    of execute → record do not double-write (idempotent). metrics=None means
    pending_sync; the enterprise sync populates metrics and flips to synced.
    """
    now = datetime.now(timezone.utc).isoformat()
    # Deterministic key from the (asset_id, event_id) pair — stable across retries.
    perf_id = "perf-" + hashlib.sha1(f"{asset_id}:{event_id}".encode()).hexdigest()[:12]

    recorded_at = now
    effective_window_start = window_start if window_start is not None else recorded_at

    doc = Performance(
        performance_id=perf_id,
        asset_id=asset_id,
        campaign_id=campaign_id,
        event_id=event_id,
        product_route=product_route,
        channels=channels_for_route(product_route),
        metrics=metrics,
        metrics_status="synced" if metrics else "pending_sync",
        window_days=7,
        window_start=effective_window_start,
        recorded_at=recorded_at,
    )

    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "performance",
        "filter": {"asset_id": asset_id, "event_id": event_id},
        "update": {"$set": doc.model_dump(mode="json")},
        "upsert": True,
    })
