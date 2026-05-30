"""Internal MongoDB wrapper for the approvals collection."""

from datetime import datetime, timezone

from src.db import _parse_docs_response, get_client
from src.models import Approval, ApprovalDecision


async def get_pending_approvals(event_id: str, limit: int = 50) -> list[Approval]:
    """Return pending approvals for an event. Event-scoped so a second batch cannot bleed in."""
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "approvals",
        "filter": {"event_id": event_id, "status": "pending"},
        "limit": limit,
    })
    docs = _parse_docs_response(envelope)
    return [Approval.model_validate({k: v for k, v in doc.items() if k != "_id"}) for doc in docs]


async def record_approval_decision(approval_id: str, decision: ApprovalDecision) -> None:
    """Bundled write: persist decision on approval + cascade to campaign/asset.

    Reads the approval document first to resolve campaign_id and asset_id for cascade.

    Cascade rules (per status machine):
      approved     → approval updated + campaign status="approved"
      rejected     → approval updated + campaign status="rejected" + asset status="rejected"
      edit_requested → approval updated only (campaign stays draft; asset unchanged)
    """
    now = datetime.now(timezone.utc).isoformat()

    # Resolve campaign_id + asset_id from the stored approval document.
    envelope = await get_client().call("find", {
        "database": "event_commerce",
        "collection": "approvals",
        "filter": {"approval_id": approval_id},
        "limit": 1,
    })
    docs = _parse_docs_response(envelope)
    campaign_id = docs[0]["campaign_id"] if docs else None
    asset_id = docs[0]["asset_id"] if docs else None

    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "approvals",
        "filter": {"approval_id": approval_id},
        "update": {"$set": {
            "status": decision.decision,
            "reviewer_notes": decision.reviewer_notes,
            "decided_at": now,
        }},
    })

    if decision.decision in ("approved", "rejected") and campaign_id:
        await get_client().call("update-many", {
            "database": "event_commerce",
            "collection": "campaigns",
            "filter": {"campaign_id": campaign_id},
            "update": {"$set": {"status": decision.decision}},
        })

    if decision.decision == "rejected" and asset_id:
        await get_client().call("update-many", {
            "database": "event_commerce",
            "collection": "assets",
            "filter": {"asset_id": asset_id},
            "update": {"$set": {"status": "rejected"}},
        })


async def reset_approval_to_pending(approval_id: str) -> None:
    """Redraft: reset approval to pending, clearing reviewer_notes and decided_at."""
    await get_client().call("update-many", {
        "database": "event_commerce",
        "collection": "approvals",
        "filter": {"approval_id": approval_id},
        "update": {"$set": {
            "status": "pending",
            "reviewer_notes": None,
            "decided_at": None,
        }},
    })
