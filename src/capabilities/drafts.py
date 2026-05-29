"""draft_campaigns_for_queue — Step 6: LLM-driven copy generation.

FunctionNode (not an LlmAgent). Reads the persisted queue from Mongo, generates
narrative-grounded copy per item via internal genai, and writes campaign + approval
documents. Reuses GEMINI_MODEL (flash-lite) — no new env var.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from google import genai
from google.genai.types import GenerateContentConfig

from src.db.assets import get_assets_for_event
from src.db.campaigns import submit_campaign_for_review
from src.db.events import get_event
from src.errors import PreconditionError
from src.models import Campaign, GeneratedCopy
from src.prompt_loader import load_prompt

_MAX_COPY_TOKENS = 1024


def _route_to_campaign_fields(product_route: str | None) -> tuple[str | None, str]:
    """Map a product_route value to (product_type, platform_target)."""
    if product_route == "poster":
        return ("poster", "shopify")
    if product_route == "tshirt":
        return ("tshirt", "shopify")
    # social_only or None (un-set defensively treated as social)
    return (None, "social")


def _recommend_timing(timeliness: float, event) -> str:
    """Deterministic timing recommendation anchored on event.start_date.

    Higher timeliness → sooner offset. Offset range: 2h (timeliness=1.0) to 72h (0.0).
    Pure: same inputs always yield the same ISO-8601 string.
    """
    start = datetime.fromisoformat(event.start_date.replace("Z", "+00:00"))
    offset_hours = 2.0 + (1.0 - timeliness) * 70.0
    recommend_at = start + timedelta(hours=offset_hours)
    return recommend_at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _draft_copy_for_asset(narrative_context: dict, item_context: dict) -> GeneratedCopy:
    """Single Gemini text call with structured output. Sync — callers wrap in asyncio.to_thread.

    This function is the Tier-1 eval-mock seam (analogous to _score_asset_with_vision).
    """
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    prompt = load_prompt("draft_campaign_copy").format(
        narrative_angle=narrative_context.get("narrative_angle", ""),
        key_figures=narrative_context.get("key_figures", ""),
        queue_rationale=item_context.get("queue_rationale", ""),
        product_route=item_context.get("product_route", ""),
        detected_subjects=item_context.get("detected_subjects", []),
    )
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GeneratedCopy,
            max_output_tokens=_MAX_COPY_TOKENS,
        ),
    )
    return GeneratedCopy.model_validate_json(response.text)


async def draft_campaigns_for_queue(event_id: str, operator_notes: dict | None = None) -> dict:
    """Generates copy + writes campaign/approval docs for every surfaced queue item.

    Reads the persisted queue from Mongo (event_id-based, D-022). Per queued asset:
    calls _draft_copy_for_asset (the eval-mock seam), derives product/platform from
    product_route, and calls submit_campaign_for_review (bundled write).

    operator_notes is reserved but unused — redraft lands in Step 7 with the HITL
    loop that defines the payload.

    Returns {"event_id", "campaign_ids", "approval_ids", "drafts"}.
    Raises PreconditionError for missing event / no scored assets / missing narrative.
    Zero surfaced assets is valid-degenerate: returns empty lists without raising.
    """
    event = await get_event(event_id)
    if event is None:
        raise PreconditionError(
            capability="draft_campaigns_for_queue",
            context=event_id,
            missing={"event": "event not found; call ingest_event_batch first"},
        )

    scored = await get_assets_for_event(event_id, status="scored")
    missing: dict[str, str] = {}
    if not scored:
        missing["scores"] = "no scored assets; call score_assets_with_vision first"
    if event.event_narrative is None:
        missing["narrative"] = "call build_event_context first"
    if missing:
        raise PreconditionError(
            capability="draft_campaigns_for_queue",
            context=event_id,
            missing=missing,
        )

    queued = sorted(
        [a for a in scored if a.queue_type is not None],
        key=lambda a: (a.queue_type or "", a.queue_rank or 0),
    )
    if not queued:
        return {"event_id": event_id, "campaign_ids": [], "approval_ids": [], "drafts": []}

    narrative_context = {
        "narrative_angle": event.event_narrative.narrative_angle,
        "key_figures": ", ".join(kf.name for kf in event.event_narrative.key_figures),
    }

    campaign_ids: list[str] = []
    approval_ids: list[str] = []
    drafts: list[dict] = []

    for asset in queued:
        detected = asset.detected_subjects or []
        detected_str = (
            ", ".join(detected)
            if detected
            else "(none — wide-angle or crowd shot; no named individual confirmed in this frame)"
        )
        item_context = {
            "queue_rationale": asset.queue_rationale or "",
            "product_route": asset.product_route or "",
            "detected_subjects": detected_str,
        }
        copy = await asyncio.to_thread(_draft_copy_for_asset, narrative_context, item_context)
        product_type, platform_target = _route_to_campaign_fields(asset.product_route)
        campaign = Campaign(
            campaign_id=str(uuid4()),
            asset_id=asset.asset_id,
            event_id=event_id,
            product_type=product_type,
            generated_copy=copy,
            platform_target=platform_target,
            timing_recommendation=_recommend_timing(event.timeliness, event),
            status="draft",
            created_at=datetime.now(timezone.utc).isoformat(),
            execution=None,
        )
        result = await submit_campaign_for_review(campaign)
        campaign_ids.append(result["campaign_id"])
        approval_ids.append(result["approval_id"])
        drafts.append({
            "asset_id": asset.asset_id,
            "product_route": asset.product_route,
            "headline": copy.headline,
            "caption": copy.caption,
            "timing_recommendation": campaign.timing_recommendation,
            "queue_rationale": asset.queue_rationale,
        })

    return {
        "event_id": event_id,
        "campaign_ids": campaign_ids,
        "approval_ids": approval_ids,
        "drafts": drafts,
    }
