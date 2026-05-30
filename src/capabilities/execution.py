"""execute_approved_campaigns — Step 7: coordinator-side execution capability.

Coordinator FunctionTool (not a workflow node). Reads approved campaigns from
Mongo (execution=None), dispatches by product_route to channel helpers, and
records results. Shopify/Printful helpers are stubbed at the seam (demo-prep
swaps the bodies); _simulate_social_post is the final form (Hard Constraint #6).
"""

import asyncio
from datetime import datetime, timezone

from google.adk.tools.tool_context import ToolContext

from src.db.assets import mark_asset_executing
from src.db.campaigns import get_approved_campaigns, record_execution_failure, record_execution_result
from src.models import ExecutionError, ExecutionResult


# ---------------------------------------------------------------------------
# External-API helpers — seam for demo-prep live wiring
# ---------------------------------------------------------------------------

def _shopify_create_product(campaign_id: str, asset_id: str, generated_copy: dict) -> dict:
    """Stub: returns a canned Shopify product payload. Live wiring is demo-prep."""
    return {
        "product_id": f"gid://shopify/Product/{campaign_id}",
        "product_url": f"https://demo.myshopify.com/products/{campaign_id}",
    }


def _printful_create_mockup(campaign_id: str, asset_id: str, product_type: str) -> dict:
    """Stub: returns a canned Printful create-mockup payload. Live wiring is demo-prep."""
    return {"task_id": f"printful-task-{campaign_id}"}


def _printful_poll_mockup(task_id: str) -> dict:
    """Stub: returns completed immediately. Live wiring is demo-prep.

    The poll loop in execute_approved_campaigns is real — only this helper body is stubbed.
    """
    return {"status": "completed", "mockup_url": f"https://printful.com/mockups/{task_id}.jpg"}


async def _simulate_social_post(
    campaign_id: str,
    asset_id: str,
    generated_copy: dict,
    content_url: str,
) -> dict:
    """Simulate a social post — NOT a stub. Simulation is social's final form (Hard Constraint #6).

    Returns a queued post package. In a production wiring this would write
    to the social collection; here it returns the package dict that the caller
    writes via record_execution_result.
    """
    return {
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "post_url": f"https://social.example.com/posts/{campaign_id}",
        "headline": generated_copy.get("headline", ""),
        "caption": generated_copy.get("caption", ""),
        "hashtags": generated_copy.get("hashtags", []),
        "content_url": content_url,
    }


# ---------------------------------------------------------------------------
# Internal poll loop for Printful mockup generation
# ---------------------------------------------------------------------------

_PRINTFUL_MAX_POLL = 10
_PRINTFUL_POLL_INTERVAL_S = 2.0


async def _printful_poll_with_retry(task_id: str) -> dict:
    """Internal async poll loop for Printful mockup completion.

    Bounded retries + timeout. The stub returns completed immediately;
    the loop structure is real so only the helper body swaps at demo-prep.
    """
    for _ in range(_PRINTFUL_MAX_POLL):
        result = await asyncio.to_thread(_printful_poll_mockup, task_id)
        if result.get("status") == "completed":
            return result
        await asyncio.sleep(_PRINTFUL_POLL_INTERVAL_S)
    raise TimeoutError(f"Printful mockup {task_id} did not complete after {_PRINTFUL_MAX_POLL} polls")


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------

async def execute_approved_campaigns(event_id: str, tool_context: ToolContext) -> dict:
    """Dispatch approved campaigns to channel helpers and record results.

    Reads approved campaigns (execution=None) from Mongo, dispatches per item
    by product_route (poster/tshirt → Shopify + Printful; social_only → social),
    and records the result or failure. Execution failures are retriable (MVP).

    Args:
        event_id: the event whose approved campaigns to execute.

    Returns:
        {"event_id", "executed": [...], "failed": [...]}
    """
    approved = await get_approved_campaigns(event_id)

    executed: list[dict] = []
    failed: list[dict] = []

    for ac in approved:
        await mark_asset_executing(ac.asset_id)
        campaign_id = ac.campaign.campaign_id
        copy = ac.campaign.generated_copy.model_dump(mode="json")

        try:
            if ac.product_route in ("poster", "tshirt"):
                shopify_result = await asyncio.to_thread(
                    _shopify_create_product, campaign_id, ac.asset_id, copy
                )
                mockup_task = await asyncio.to_thread(
                    _printful_create_mockup, campaign_id, ac.asset_id, ac.product_route or ""
                )
                printful_result = await _printful_poll_with_retry(mockup_task["task_id"])
                result = ExecutionResult(
                    shopify=shopify_result,
                    printful={"task_id": mockup_task["task_id"], "mockup_url": printful_result.get("mockup_url")},
                    social=None,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                # social_only or None (defensive)
                social_result = await _simulate_social_post(
                    campaign_id, ac.asset_id, copy,
                    content_url=ac.campaign.generated_copy.headline,
                )
                result = ExecutionResult(
                    shopify=None,
                    printful=None,
                    social=social_result,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )

            await record_execution_result(ac.asset_id, campaign_id, result)
            executed.append({
                "campaign_id": campaign_id,
                "asset_id": ac.asset_id,
                "product_route": ac.product_route,
                "channels": {k: v for k, v in result.model_dump(mode="json").items() if v and k != "executed_at"},
            })

        except Exception as exc:
            error = ExecutionError(
                channel=ac.product_route or "unknown",
                message=str(exc),
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
            await record_execution_failure(ac.asset_id, campaign_id, error)
            failed.append({"campaign_id": campaign_id, "asset_id": ac.asset_id, "error": str(exc)})

    return {"event_id": event_id, "executed": executed, "failed": failed}
