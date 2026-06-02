"""atlas_state query — returns the AtlasState shape for the SSE pipeline_complete panel."""

import re

from src.db import _parse_docs_response, get_client


async def _count(collection: str) -> int:
    """Return document count for a collection in the event_commerce database."""
    envelope = await get_client().call("count", {
        "database": "event_commerce",
        "collection": collection,
    })
    for item in envelope.get("content", []):
        text = item.get("text", "")
        m = re.search(r"(\d+)", text)
        if m:
            return int(m.group(1))
    return 0


async def _count_approvals_by_status() -> dict[str, int]:
    """Return counts of approvals grouped by status."""
    envelope = await get_client().call("aggregate", {
        "database": "event_commerce",
        "collection": "approvals",
        "pipeline": [
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        ],
    })
    docs = _parse_docs_response(envelope)
    by_status: dict[str, int] = {}
    for doc in docs:
        status = doc.get("_id") or "unknown"
        by_status[status] = doc.get("n", 0)
    return by_status


async def _count_performance_metrics() -> dict:
    """Return total performance rows and a metrics_status label."""
    envelope = await get_client().call("count", {
        "database": "event_commerce",
        "collection": "performance",
    })
    total = 0
    for item in envelope.get("content", []):
        text = item.get("text", "")
        m = re.search(r"(\d+)", text)
        if m:
            total = int(m.group(1))
            break
    return {"total": total, "metrics_status": "pending_sync" if total > 0 else "none"}


async def get_atlas_state() -> dict:
    """Return AtlasState dict matching the frontend AtlasState interface."""
    events, assets, campaigns, approvals_status, perf = await _gather(
        _count("events"),
        _count("assets"),
        _count("campaigns"),
        _count_approvals_by_status(),
        _count_performance_metrics(),
    )
    total_approvals = sum(approvals_status.values())
    return {
        "events": events,
        "assets": assets,
        "campaigns": campaigns,
        "approvals": {
            "total": total_approvals,
            "approved": approvals_status.get("approved", 0),
            "rejected": approvals_status.get("rejected", 0),
            "edit_requested": approvals_status.get("edit_requested", 0),
        },
        "performance": perf,
    }


async def _gather(*coros):
    """Run coroutines concurrently and return results in order."""
    import asyncio
    return await asyncio.gather(*coros)
