"""execute_approved_campaigns — Step 7: coordinator-side execution capability.

Coordinator FunctionTool (not a workflow node). Reads approved campaigns from
Mongo (execution=None), dispatches by product_route to channel helpers, and
records results. Shopify/Printful helpers are stubbed at the seam (demo-prep
swaps the bodies); _simulate_social_post is the final form (Hard Constraint #6).

Preview mode: when Printful creds are absent, Gemini generates the mockup image
server-side. Bytes are stored in src/mockup_store and served by the API at
GET /api/mockup/{asset_id}.
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from src.db.assets import get_assets_by_ids, mark_asset_executing
from src.db.campaigns import get_approved_campaigns, record_execution_failure, record_execution_result
from src.mockup_store import store_mockup
from src.models import ExecutionError, ExecutionResult
from src.sse import get_queue

# Blank shirt asset used for Gemini t-shirt mockup generation (preview mode).
_SHIRT_BASE = Path(__file__).parent.parent.parent / "spike" / "output" / "shirt_base.jpg"

_MOCKUP_PROMPT = """\
You are given two images:
  Image 1: a blank white t-shirt.
  Image 2: a photograph that is the artwork to be screen-printed on the shirt.

Task: output a single product photo of the t-shirt from Image 1 with the photograph \
from Image 2 printed on the chest as a professional DTG (direct-to-garment) garment print.

Print physics — this is critical:
- The print follows the shirt's physical surface: where the fabric creases or folds, \
the print image bends and distorts with it, as if the ink was applied to the fabric before it was folded.
- The cotton weave texture is subtly visible through the ink.
- Absolutely zero white halo, glow, outline, or border around the print edges.

Background: Place the t-shirt on a clean, solid light-grey background (#CCCCCC).
Output: a single product-photography-style image of the finished t-shirt only.
"""


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
    """Stub: returns completed immediately. Live wiring is demo-prep."""
    return {"status": "completed", "mockup_url": f"https://printful.com/mockups/{task_id}.jpg"}


async def _simulate_social_post(
    campaign_id: str,
    asset_id: str,
    generated_copy: dict,
    content_url: str,
) -> dict:
    """Simulate a social post — NOT a stub. Simulation is social's final form (Hard Constraint #6)."""
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
# Preview-mode Gemini mockup generation
# ---------------------------------------------------------------------------

def _has_printful_creds() -> bool:
    return bool(os.environ.get("PRINTFUL_API_KEY"))


async def _generate_preview_mockup(asset_id: str, content_url: str, product_type: str) -> "bytes | None":
    """Generate a preview mockup via Gemini and store bytes in src/mockup_store.

    For t-shirts: Gemini image generation (blank shirt + design photo).
    For posters: fetch and return the source image bytes directly (photo IS the poster).
    Returns None on any failure (caller emits nothing; UI spinner stays).
    """
    try:
        if product_type == "tshirt":
            return await asyncio.to_thread(_gemini_tshirt_mockup, content_url)
        elif product_type == "poster":
            return await asyncio.to_thread(_fetch_image_bytes, content_url)
    except Exception:  # noqa: BLE001
        return None
    return None


def _fetch_image_bytes(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        return Path(url).read_bytes()
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _gemini_tshirt_mockup(design_url: str) -> bytes:
    """Synchronous Gemini call — run via asyncio.to_thread."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    if not _SHIRT_BASE.exists():
        raise FileNotFoundError(f"blank shirt not found: {_SHIRT_BASE}")

    client = genai.Client(api_key=api_key)
    shirt_bytes = _SHIRT_BASE.read_bytes()
    design_bytes = _fetch_image_bytes(design_url)

    response = client.models.generate_content(
        model="gemini-3-pro-image",
        contents=[
            types.Part.from_bytes(data=shirt_bytes, mime_type="image/jpeg"),
            types.Part.from_bytes(data=design_bytes, mime_type="image/jpeg"),
            types.Part(text=_MOCKUP_PROMPT),
        ],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            return part.inline_data.data

    raise RuntimeError("Gemini returned no image data")


# ---------------------------------------------------------------------------
# Internal poll loop for Printful mockup generation
# ---------------------------------------------------------------------------

_PRINTFUL_MAX_POLL = 10
_PRINTFUL_POLL_INTERVAL_S = 2.0


async def _printful_poll_with_retry(task_id: str) -> dict:
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

    Emits SSE events for capability lifecycle, execution_evidence (before mockup URLs),
    and mockup_resolved per commerce item. In preview mode (no Printful creds), mockups
    are generated via Gemini image generation.
    """
    sse_session_id = tool_context.state.get("_sse_session_id")
    api_base = os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:8000")

    def _emit(event_type: str, payload: dict) -> None:
        if not sse_session_id:
            return
        q = get_queue(sse_session_id)
        if q is not None:
            q.put_nowait({"type": event_type, "payload": payload})

    _emit("capability_started", {"capability": "execute_approved_campaigns"})

    approved = await get_approved_campaigns(event_id)

    # Fetch assets for content_url (not on ApprovedCampaign join view)
    asset_ids = [ac.asset_id for ac in approved]
    assets = await get_assets_by_ids(asset_ids)
    asset_by_id = {a.asset_id: a for a in assets}

    executed: list[dict] = []
    failed: list[dict] = []

    # Items that need mockup resolution (commerce items)
    mockup_items: list[dict] = []  # {asset_id, content_url, product_type}

    for ac in approved:
        await mark_asset_executing(ac.asset_id)
        campaign_id = ac.campaign.campaign_id
        copy = ac.campaign.generated_copy.model_dump(mode="json")
        asset = asset_by_id.get(ac.asset_id)
        content_url = asset.content_url if asset else ""

        try:
            if ac.product_route in ("poster", "tshirt"):
                shopify_result = await asyncio.to_thread(
                    _shopify_create_product, campaign_id, ac.asset_id, copy
                )

                if _has_printful_creds():
                    mockup_task = await asyncio.to_thread(
                        _printful_create_mockup, campaign_id, ac.asset_id, ac.product_route or ""
                    )
                    printful_result = await _printful_poll_with_retry(mockup_task["task_id"])
                    mockup_url = printful_result.get("mockup_url", "")
                else:
                    # Preview mode: generate mockup after evidence is emitted
                    mockup_url = None
                    mockup_items.append({
                        "asset_id": ac.asset_id,
                        "content_url": content_url,
                        "product_type": ac.product_route,
                    })

                result = ExecutionResult(
                    shopify=shopify_result,
                    printful={"mockup_url": mockup_url} if mockup_url else None,
                    social=None,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
                executed.append({
                    "campaign_id": campaign_id,
                    "asset_id": ac.asset_id,
                    "product_route": ac.product_route,
                    "product_id": shopify_result.get("product_id", ""),
                    "product_url": shopify_result.get("product_url", ""),
                    "content_url": content_url,
                    "channels": {
                        k: v for k, v in result.model_dump(mode="json").items()
                        if v and k != "executed_at"
                    },
                })
            else:
                social_result = await _simulate_social_post(
                    campaign_id, ac.asset_id, copy,
                    content_url=content_url,
                )
                result = ExecutionResult(
                    shopify=None,
                    printful=None,
                    social=social_result,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
                executed.append({
                    "campaign_id": campaign_id,
                    "asset_id": ac.asset_id,
                    "product_route": ac.product_route,
                    "content_url": content_url,
                    "channels": {"social": social_result},
                })

            await record_execution_result(ac.asset_id, campaign_id, result)

        except Exception as exc:
            error = ExecutionError(
                channel=ac.product_route or "unknown",
                message=str(exc),
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
            await record_execution_failure(ac.asset_id, campaign_id, error)
            failed.append({"campaign_id": campaign_id, "asset_id": ac.asset_id, "error": str(exc)})

    n_exec = len(executed)
    _emit("capability_completed", {
        "capability": "execute_approved_campaigns",
        "resultSummary": f"{n_exec} campaign{'s' if n_exec != 1 else ''} dispatched",
    })

    # Build and emit execution_evidence (without mockup URLs — they follow as mockup_resolved)
    shopify_products = [
        {
            "assetId": e["asset_id"],
            "productId": e.get("product_id", ""),
            "title": _title_for_route(e.get("product_route")),
            "url": e.get("product_url", ""),
            "productType": e.get("product_route"),
            "photoUrl": e.get("content_url", ""),
            # mockupUrl intentionally absent — resolves via mockup_resolved below
        }
        for e in executed
        if e.get("product_route") in ("poster", "tshirt")
    ]
    social_posts = [
        {
            "assetId": e["asset_id"],
            "photoUrl": e.get("content_url", ""),
            "caption": e["channels"]["social"].get("caption", ""),
            "hashtags": e["channels"]["social"].get("hashtags", []),
            "status": "queued",
        }
        for e in executed
        if e.get("channels", {}).get("social")
    ]
    mode = "live" if _has_printful_creds() else "preview"
    _emit("execution_evidence", {
        "mode": mode,
        "shopifyProducts": shopify_products,
        "socialPosts": social_posts,
    })

    # Preview mode: resolve mockups sequentially and emit mockup_resolved per item
    for mi in mockup_items:
        asset_id = mi["asset_id"]
        # content_url from executed items (more reliable than campaign copy field)
        content_url = next(
            (e.get("content_url", "") for e in executed if e["asset_id"] == asset_id),
            mi.get("content_url", ""),
        )
        img_bytes = await _generate_preview_mockup(asset_id, content_url, mi["product_type"])
        if img_bytes:
            store_mockup(asset_id, img_bytes)
            _emit("mockup_resolved", {
                "assetId": asset_id,
                "mockupUrl": f"{api_base}/api/mockup/{asset_id}",
            })

    return {"event_id": event_id, "executed": executed, "failed": failed}


def _title_for_route(product_route: "str | None") -> str:
    if product_route == "poster":
        return "Match Poster"
    if product_route == "tshirt":
        return "Match T-Shirt"
    return "Product"
