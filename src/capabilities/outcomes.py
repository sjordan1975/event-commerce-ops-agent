"""record_outcomes capability (capability 9, coordinator-plane FunctionTool)."""

from google.adk.tools.tool_context import ToolContext

from src.db.assets import get_assets_for_event
from src.db.campaigns import get_campaigns_by_ids
from src.db.performance import channels_for_route, record_performance


async def record_outcomes(event_id: str, tool_context: ToolContext) -> dict:
    """Record post-execution outcomes for an event. Call this ONCE after
    execute_approved_campaigns has published the approved campaigns. Writes one
    performance-tracking record per published asset, linking it to its campaign and
    opening the 7-day measurement window. Engagement and conversion metrics are NOT
    populated here — they are synced later by an external process; this records that
    each published asset is now tracked and pending that sync. If nothing has been
    published for the event, it records nothing and reports so. Makes no external
    API call. After this returns, report to the operator and stop.
    """
    published = await get_assets_for_event(event_id, status="published")

    if not published:
        return {"status": "nothing_to_record", "event_id": event_id}

    campaign_ids = [a.campaign_id for a in published if a.campaign_id]
    campaigns = await get_campaigns_by_ids(campaign_ids)
    by_campaign_id = {c.campaign_id: c for c in campaigns}

    recorded = []
    for asset in published:
        campaign = by_campaign_id.get(asset.campaign_id) if asset.campaign_id else None
        execution = campaign.execution if campaign else None
        window_start = execution.get("executed_at") if isinstance(execution, dict) else None

        await record_performance(
            asset_id=asset.asset_id,
            campaign_id=asset.campaign_id or "",
            event_id=event_id,
            product_route=asset.product_route,
            window_start=window_start,
            metrics=None,
        )

        recorded.append({
            "asset_id": asset.asset_id,
            "campaign_id": asset.campaign_id,
            "channels": channels_for_route(asset.product_route),
        })

    return {
        "status": "recorded",
        "event_id": event_id,
        "count": len(recorded),
        "pending_sync": True,
        "records": recorded,
    }
