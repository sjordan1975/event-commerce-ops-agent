"""execute_approved_campaigns — Step 7: coordinator-side execution capability.

Coordinator FunctionTool (not a workflow node). Reads approved campaigns from
Mongo (execution=None), dispatches by product_route to channel helpers, and
records results.

Commerce route (poster/tshirt): Gemini generates a mockup image, which is
uploaded directly to Shopify via staged upload and attached as the product image.
A single _shopify_create_product call handles mockup generation, upload, product
creation, and media attachment, returning product_id, product_url, and mockup_url.

Preview mode (no Shopify creds): mockup bytes are stored in src/mockup_store
and served by the API at GET /api/mockup/{asset_id}.

Social route: simulated — Hard Constraint #6.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

from google.adk.tools.tool_context import ToolContext

from src.db.assets import get_assets_by_ids, mark_asset_executing
from src.db.campaigns import get_approved_campaigns, record_execution_failure, record_execution_result
from src.mockup_store import store_mockup
from src.models import ExecutionError, ExecutionResult
from src.sse import get_queue

# Blank shirt asset used for Gemini t-shirt mockup generation.
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
# Credential gate
# ---------------------------------------------------------------------------

def _has_shopify_creds() -> bool:
    return bool(
        os.environ.get("SHOPIFY_STORE_URL")
        and os.environ.get("SHOPIFY_CLIENT_ID")
        and os.environ.get("SHOPIFY_CLIENT_SECRET")
    )


# ---------------------------------------------------------------------------
# Shopify token cache — client credentials grant returns a 24-hour token.
# ---------------------------------------------------------------------------

_shopify_token_cache: dict = {}
_SHOPIFY_TOKEN_TTL = 23 * 3600


def _shopify_get_token() -> str:
    now = time.time()
    if _shopify_token_cache.get("token") and now - _shopify_token_cache.get("fetched_at", 0) < _SHOPIFY_TOKEN_TTL:
        return _shopify_token_cache["token"]
    store_url = os.environ["SHOPIFY_STORE_URL"].rstrip("/")
    resp = httpx.post(
        f"{store_url}/admin/oauth/access_token",
        json={
            "client_id": os.environ["SHOPIFY_CLIENT_ID"],
            "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _shopify_token_cache["token"] = token
    _shopify_token_cache["fetched_at"] = now
    return token


# ---------------------------------------------------------------------------
# Shopify GraphQL mutations
# ---------------------------------------------------------------------------

_SHOPIFY_API_VERSION = "2026-04"

_SHOPIFY_PRODUCT_CREATE = """
mutation productCreate($input: ProductInput!) {
  productCreate(input: $input) {
    product { id handle }
    userErrors { field message }
  }
}
"""

_SHOPIFY_STAGED_UPLOADS_CREATE = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets {
      url
      resourceUrl
      parameters { name value }
    }
    userErrors { field message }
  }
}
"""

_SHOPIFY_PRODUCT_CREATE_MEDIA = """
mutation productCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { id status }
    mediaUserErrors { field message code }
  }
}
"""


# ---------------------------------------------------------------------------
# Mockup generation — sync, called via asyncio.to_thread
# ---------------------------------------------------------------------------

def _fetch_image_bytes(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        return Path(url).read_bytes()
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _gemini_tshirt_mockup(design_url: str) -> bytes:
    """Generate a t-shirt mockup via Gemini image generation."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    if not _SHIRT_BASE.exists():
        raise FileNotFoundError(f"blank shirt not found: {_SHIRT_BASE}")

    label = Path(design_url.split("?")[0]).name
    logger.info("tshirt_mockup start  design=%s", label)
    t0 = time.perf_counter()
    client = genai.Client(api_key=api_key)
    shirt_bytes = _SHIRT_BASE.read_bytes()
    design_bytes = _fetch_image_bytes(design_url)

    response = client.models.generate_content(
        model=os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3-pro-image"),
        contents=[
            types.Part.from_bytes(data=shirt_bytes, mime_type="image/jpeg"),
            types.Part.from_bytes(data=design_bytes, mime_type="image/jpeg"),
            types.Part(text=_MOCKUP_PROMPT),
        ],
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            data = part.inline_data.data
            logger.info("tshirt_mockup done   design=%s bytes=%d latency=%.1fs",
                        label, len(data), time.perf_counter() - t0)
            return data
    raise RuntimeError("Gemini returned no image data")


def _generate_mockup_bytes(content_url: str, product_type: str) -> bytes | None:
    """Generate mockup bytes for a product type. Returns None on failure."""
    try:
        if product_type == "tshirt":
            return _gemini_tshirt_mockup(content_url)
        else:
            # poster: the source photo is the product image
            return _fetch_image_bytes(content_url)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shopify staged upload — sync, called via asyncio.to_thread
# ---------------------------------------------------------------------------

def _shopify_staged_upload(img_bytes: bytes, token: str, endpoint: str) -> str:
    """Upload image bytes via Shopify staged upload. Returns the resourceUrl."""
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    resp = httpx.post(endpoint, json={
        "query": _SHOPIFY_STAGED_UPLOADS_CREATE,
        "variables": {"input": [{
            "filename": "mockup.jpg",
            "mimeType": "image/jpeg",
            "resource": "PRODUCT_IMAGE",
            "httpMethod": "POST",
        }]},
    }, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("data", {}).get("stagedUploadsCreate", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"stagedUploadsCreate errors: {errors}")

    target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]
    upload_url = target["url"]
    resource_url = target["resourceUrl"]
    params = {p["name"]: p["value"] for p in target["parameters"]}

    # S3/GCS multipart: parameters first, file last
    form_fields = [(k, (None, v)) for k, v in params.items()]
    form_fields.append(("file", ("mockup.jpg", img_bytes, "image/jpeg")))
    upload_resp = httpx.post(upload_url, files=form_fields, timeout=60)
    if upload_resp.status_code >= 400:
        raise RuntimeError(f"Staged upload failed HTTP {upload_resp.status_code}: {upload_resp.text[:200]}")

    return resource_url


# ---------------------------------------------------------------------------
# External-API helpers — credential-gated; preview stub when creds absent
# ---------------------------------------------------------------------------

def _shopify_create_product(
    campaign_id: str,
    asset_id: str,
    generated_copy: dict,
    content_url: str = "",
    product_type: str = "poster",
) -> dict:
    """Generate mockup, create Shopify draft product, attach mockup as product image.

    Live mode (Shopify creds present): mockup → staged upload → productCreate →
    productCreateMedia. Returns product_id, product_url, mockup_url (Shopify-hosted).

    Preview mode: mockup bytes stored locally, served at /api/mockup/{asset_id}.
    """
    img_bytes = _generate_mockup_bytes(content_url, product_type)

    if not _has_shopify_creds():
        # Preview mode — store locally and return stub product URL
        api_base = os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:8000")
        mockup_url = ""
        if img_bytes:
            store_mockup(asset_id, img_bytes)
            mockup_url = f"{api_base}/api/mockup/{asset_id}"
        return {
            "product_id": f"gid://shopify/Product/{campaign_id}",
            "product_url": f"https://demo.myshopify.com/products/{campaign_id}",
            "mockup_url": mockup_url,
            "preview": True,
        }

    store_url = os.environ["SHOPIFY_STORE_URL"].rstrip("/")
    token = _shopify_get_token()
    endpoint = f"{store_url}/admin/api/{_SHOPIFY_API_VERSION}/graphql.json"
    gql_headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    title = generated_copy.get("headline") or f"Event Product {campaign_id[:8]}"
    description = generated_copy.get("caption", "")

    # Create the product
    resp = httpx.post(endpoint, json={
        "query": _SHOPIFY_PRODUCT_CREATE,
        "variables": {"input": {"title": title, "descriptionHtml": description, "status": "DRAFT"}},
    }, headers=gql_headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("data", {}).get("productCreate", {}).get("userErrors", [])
    if errors:
        raise RuntimeError(f"Shopify productCreate errors: {errors}")
    product = data["data"]["productCreate"]["product"]
    product_id = product["id"]
    numeric_id = product_id.split("/")[-1]
    product_url = f"{store_url}/admin/products/{numeric_id}"

    # Upload mockup and attach as product image
    mockup_url = ""
    if img_bytes:
        try:
            resource_url = _shopify_staged_upload(img_bytes, token, endpoint)
            media_resp = httpx.post(endpoint, json={
                "query": _SHOPIFY_PRODUCT_CREATE_MEDIA,
                "variables": {
                    "productId": product_id,
                    "media": [{"originalSource": resource_url, "mediaContentType": "IMAGE"}],
                },
            }, headers=gql_headers, timeout=30)
            media_resp.raise_for_status()
            media_errors = media_resp.json().get("data", {}).get("productCreateMedia", {}).get("mediaUserErrors", [])
            if not media_errors:
                mockup_url = resource_url
            else:
                logger.warning("productCreateMedia errors: %s", media_errors)
        except Exception as exc:
            logger.warning("mockup upload failed (product still created): %s", exc)

    return {"product_id": product_id, "product_url": product_url, "mockup_url": mockup_url}


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
# Capability
# ---------------------------------------------------------------------------

async def execute_approved_campaigns(event_id: str, tool_context: ToolContext) -> dict:
    """Dispatch approved campaigns to channel helpers and record results.

    Commerce items (poster/tshirt): Gemini mockup → Shopify staged upload →
    productCreate → productCreateMedia. Emits mockup_resolved per item as
    soon as the product is created (mockup_url is synchronous, not deferred).

    Social items: simulated post package written to Mongo.
    """
    sse_session_id = tool_context.state.get("_sse_session_id")

    def _emit(event_type: str, payload: dict) -> None:
        if not sse_session_id:
            return
        q = get_queue(sse_session_id)
        if q is not None:
            q.put_nowait({"type": event_type, "payload": payload})

    _emit("capability_started", {"capability": "execute_approved_campaigns"})

    approved = await get_approved_campaigns(event_id)

    asset_ids = [ac.asset_id for ac in approved]
    assets = await get_assets_by_ids(asset_ids)
    asset_by_id = {a.asset_id: a for a in assets}

    executed: list[dict] = []
    failed: list[dict] = []

    for ac in approved:
        await mark_asset_executing(ac.asset_id)
        campaign_id = ac.campaign.campaign_id
        copy = ac.campaign.generated_copy.model_dump(mode="json")
        asset = asset_by_id.get(ac.asset_id)
        content_url = asset.content_url if asset else ""

        try:
            if ac.product_route in ("poster", "tshirt"):
                shopify_result = await asyncio.to_thread(
                    _shopify_create_product,
                    campaign_id, ac.asset_id, copy, content_url, ac.product_route or "poster",
                )
                result = ExecutionResult(
                    shopify=shopify_result,
                    printful=None,
                    social=None,
                    executed_at=datetime.now(timezone.utc).isoformat(),
                )
                executed.append({
                    "campaign_id": campaign_id,
                    "asset_id": ac.asset_id,
                    "product_route": ac.product_route,
                    "product_id": shopify_result.get("product_id", ""),
                    "product_url": shopify_result.get("product_url", ""),
                    "mockup_url": shopify_result.get("mockup_url", ""),
                    "content_url": content_url,
                    "channels": {"shopify": shopify_result},
                })
                # mockup_url is available immediately — emit now, not deferred
                if shopify_result.get("mockup_url"):
                    _emit("mockup_resolved", {
                        "assetId": ac.asset_id,
                        "mockupUrl": shopify_result["mockup_url"],
                    })
            else:
                social_result = await _simulate_social_post(
                    campaign_id, ac.asset_id, copy, content_url=content_url,
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

    shopify_products = [
        {
            "assetId": e["asset_id"],
            "productId": e.get("product_id", ""),
            "title": _title_for_route(e.get("product_route")),
            "url": e.get("product_url", ""),
            "productType": e.get("product_route"),
            "photoUrl": e.get("content_url", ""),
            "mockupUrl": e.get("mockup_url", ""),
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
    mode = "live" if _has_shopify_creds() else "preview"
    _emit("execution_evidence", {
        "mode": mode,
        "shopifyProducts": shopify_products,
        "socialPosts": social_posts,
    })

    return {"event_id": event_id, "executed": executed, "failed": failed}


def _title_for_route(product_route: "str | None") -> str:
    if product_route == "poster":
        return "Match Poster"
    if product_route == "tshirt":
        return "Match T-Shirt"
    return "Product"
