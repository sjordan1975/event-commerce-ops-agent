"""Internal MongoDB wrapper for the performance collection."""

from src.db import _parse_docs_response, get_client

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
