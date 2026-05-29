"""Internal MongoDB wrapper for campaigns and approvals collections."""

from datetime import datetime, timezone
from uuid import uuid4

from src.db import get_client
from src.models import Campaign


async def submit_campaign_for_review(campaign: Campaign) -> dict:
    """Bundled write: insert campaign, transition asset status, insert pending approval.

    Three sequential MCP calls (no transaction). Returns {"campaign_id", "approval_id"}.
    reviewer_notes is not an input — approvals are always created pending with no notes.
    """
    approval_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    await get_client().call("insert-many", {
        "database": "event_commerce",
        "collection": "campaigns",
        "documents": [campaign.model_dump(mode="json")],
    })

    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": campaign.asset_id},
        "update": {"$set": {"status": "campaign_draft_created", "campaign_id": campaign.campaign_id}},
    })

    await get_client().call("insert-many", {
        "database": "event_commerce",
        "collection": "approvals",
        "documents": [{
            "approval_id": approval_id,
            "campaign_id": campaign.campaign_id,
            "asset_id": campaign.asset_id,
            "status": "pending",
            "reviewer_notes": None,
            "created_at": now,
            "decided_at": None,
        }],
    })

    return {"campaign_id": campaign.campaign_id, "approval_id": approval_id}
