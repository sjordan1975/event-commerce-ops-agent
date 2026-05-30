"""Internal MongoDB wrapper for campaigns and approvals collections."""

from datetime import datetime, timezone
from uuid import uuid4

from src.db import _parse_docs_response, get_client
from src.models import Approval, ApprovedCampaign, Campaign, ExecutionError, ExecutionResult


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
            "event_id": campaign.event_id,
            "status": "pending",
            "reviewer_notes": None,
            "created_at": now,
            "decided_at": None,
        }],
    })

    return {"campaign_id": campaign.campaign_id, "approval_id": approval_id}


async def get_approved_campaigns(event_id: str, limit: int = 50) -> list[ApprovedCampaign]:
    """Return approved campaigns pending execution for an event.

    Joins approvals (status=approved) → campaigns; filters execution=None so
    already-executed items are not re-picked (idempotent re-run support).
    Event-scoped.
    """
    approval_envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "approvals",
        "filter": {"event_id": event_id, "status": "approved"},
        "limit": limit,
    })
    approval_docs = _parse_docs_response(approval_envelope)
    if not approval_docs:
        return []

    campaign_ids = [doc["campaign_id"] for doc in approval_docs]
    campaign_envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "campaigns",
        "filter": {"campaign_id": {"$in": campaign_ids}, "execution": None},
    })
    campaign_docs = _parse_docs_response(campaign_envelope)
    campaign_by_id = {
        doc["campaign_id"]: Campaign.model_validate({k: v for k, v in doc.items() if k != "_id"})
        for doc in campaign_docs
    }

    result = []
    for a_doc in approval_docs:
        campaign = campaign_by_id.get(a_doc["campaign_id"])
        if campaign is None:
            continue  # already executed or missing; skip
        result.append(ApprovedCampaign(
            approval_id=a_doc["approval_id"],
            campaign=campaign,
            asset_id=a_doc["asset_id"],
            product_route=_route_from_campaign(campaign),
        ))
    return result


async def get_edit_requested_campaigns(event_id: str) -> list[ApprovedCampaign]:
    """Return campaigns with edit_requested status for an event (redraft input).

    Joins approvals (status=edit_requested) → campaigns. Carries reviewer_notes
    from the approval doc so the redraft path can inject them into item_context.
    Event-scoped.
    """
    approval_envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "approvals",
        "filter": {"event_id": event_id, "status": "edit_requested"},
    })
    approval_docs = _parse_docs_response(approval_envelope)
    if not approval_docs:
        return []

    campaign_ids = [doc["campaign_id"] for doc in approval_docs]
    campaign_envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "campaigns",
        "filter": {"campaign_id": {"$in": campaign_ids}},
    })
    campaign_docs = _parse_docs_response(campaign_envelope)
    campaign_by_id = {
        doc["campaign_id"]: Campaign.model_validate({k: v for k, v in doc.items() if k != "_id"})
        for doc in campaign_docs
    }

    result = []
    for a_doc in approval_docs:
        campaign = campaign_by_id.get(a_doc["campaign_id"])
        if campaign is None:
            continue
        result.append(ApprovedCampaign(
            approval_id=a_doc["approval_id"],
            campaign=campaign,
            asset_id=a_doc["asset_id"],
            product_route=_route_from_campaign(campaign),
            reviewer_notes=a_doc.get("reviewer_notes"),
        ))
    return result


async def overwrite_campaign_draft(campaign: Campaign) -> None:
    """Redraft: replace generated_copy on the existing campaign document.

    Bumps created_at to signal the revision; asset status stays campaign_draft_created.
    """
    now = datetime.now(timezone.utc).isoformat()
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "campaigns",
        "filter": {"campaign_id": campaign.campaign_id},
        "update": {"$set": {
            "generated_copy": campaign.generated_copy.model_dump(mode="json"),
            "created_at": now,
        }},
    })


async def get_campaigns_by_ids(campaign_ids: list[str]) -> list[Campaign]:
    """Fetch campaigns by a list of campaign_ids (display-batch join helper)."""
    if not campaign_ids:
        return []
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "campaigns",
        "filter": {"campaign_id": {"$in": campaign_ids}},
    })
    docs = _parse_docs_response(envelope)
    return [Campaign.model_validate({k: v for k, v in doc.items() if k != "_id"}) for doc in docs]


async def record_execution_result(asset_id: str, campaign_id: str, result: ExecutionResult) -> None:
    """Bundled write: asset → published + published_urls; campaign → executed + execution."""
    published_urls: dict = {}
    if result.shopify:
        published_urls["shopify"] = result.shopify.get("product_url")
    if result.printful:
        published_urls["printful"] = result.printful.get("mockup_url")
    if result.social:
        published_urls["social"] = result.social.get("post_url")

    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {"status": "published", "published_urls": published_urls}},
    })
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "campaigns",
        "filter": {"campaign_id": campaign_id},
        "update": {"$set": {"status": "executed", "execution": result.model_dump(mode="json")}},
    })


async def record_execution_failure(asset_id: str, campaign_id: str, error: ExecutionError) -> None:
    """Retriable failure: leave campaign.execution=None and approval=approved for re-run.

    Reverts asset from executing so it is re-pickable (campaign.execution stays None,
    so get_approved_campaigns re-picks it on next run). Not a terminal failed state.
    campaign.execution is intentionally NOT written — its absence is the re-pick signal.
    """
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "assets",
        "filter": {"asset_id": asset_id},
        "update": {"$set": {"status": "campaign_draft_created"}},
    })
    # Log the failure detail without modifying campaign.execution (must stay None for retry).
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "campaigns",
        "filter": {"campaign_id": campaign_id},
        "update": {"$set": {"status": "execution_failed_retryable"}},
    })


def _route_from_campaign(campaign: Campaign) -> str | None:
    """Derive product_route from campaign fields (reverses Step 6 route→campaign mapping)."""
    if campaign.product_type in ("poster", "tshirt"):
        return campaign.product_type
    if campaign.platform_target == "social":
        return "social_only"
    return None
