"""score_assets_with_vision — Step 4 capability: Gemini Vision 5-dimensional scoring."""

import asyncio
import os

from google import genai
from google.genai import types as genai_types

from src.db.assets import get_assets_for_event, save_asset_scores
from src.db.events import get_event
from src.errors import PreconditionError
from src.images import image_as_part
from src.models import VisionScoringOutput
from src.prompt_loader import load_prompt


def _score_asset_with_vision(image_url: str, event_context: dict) -> VisionScoringOutput:
    """Single Gemini Vision call with structured output. Sync — callers wrap in asyncio.to_thread."""
    api_key = os.environ["GOOGLE_API_KEY"]
    model = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash")

    client = genai.Client(api_key=api_key)
    image_part = image_as_part(image_url)
    prompt = load_prompt("score_asset_with_vision").format(**event_context)

    response = client.models.generate_content(
        model=model,
        contents=[image_part, prompt],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VisionScoringOutput,
        ),
    )
    return VisionScoringOutput.model_validate_json(response.text)


async def _build_event_context_payload(event_id: str) -> dict:
    """Read event + narrative, return a dict for prompt format substitution."""
    event = await get_event(event_id)
    if event.event_narrative is not None:
        narrative_angle = event.event_narrative.narrative_angle
        key_figure_names = ", ".join(kf.name for kf in event.event_narrative.key_figures)
    else:
        narrative_angle = "(unavailable)"
        key_figure_names = "(none)"
    return {
        "outcome_type": event.outcome_type,
        "final_score": event.final_score,
        "narrative_angle": narrative_angle,
        "key_figure_names": key_figure_names,
    }


async def score_assets_with_vision(event_id: str) -> dict:
    """Scores every asset on the event along five dimensions via Gemini Vision.

    For every asset on the event without an existing scores block, calls
    Gemini Vision once with the image bytes + a small event-context block.
    The model returns:
      - scores: AssetScores with five [0,1] dimensions (D-017 dual-job):
          quality_score, merch_score        — technical fitness
          emotional_score, social_score,
          identity_score                    — commercial signal
      - detected_subjects: list[str] of named players / people visible in the frame
        (empty when no recognizable subject is present)

    Persists both onto the asset document and transitions status to "scored".
    Idempotent — assets that already carry a scores block are skipped on re-run.

    Returns {"event_id": str, "scored": list[{asset_id, scores, detected_subjects}]}.

    Raises PreconditionError if the event has no assets (call ingest_event_batch
    first). Tolerates a missing event_narrative — uses minimal event context in
    that case, but D-024 graph order ensures the narrative is normally present.

    Consumed by propose_review_queue (required precondition — scores for quality
    gate + ranking; detected_subjects for identity composition with narrative
    key_figures) and draft_campaigns_for_queue (reads asset.scores for in-prompt
    routing-recommendation ranking)."""
    assets = await get_assets_for_event(event_id)
    if not assets:
        raise PreconditionError(
            capability="score_assets_with_vision",
            context=event_id,
            missing={"assets": "no assets for event; call ingest_event_batch first"},
        )

    event_context = await _build_event_context_payload(event_id)

    for asset in assets:
        if asset.scores is not None:
            continue
        output = await asyncio.to_thread(_score_asset_with_vision, asset.content_url, event_context)
        await save_asset_scores(asset.asset_id, output.scores, output.detected_subjects)
        asset.scores = output.scores
        asset.detected_subjects = output.detected_subjects

    return {
        "event_id": event_id,
        "scored": [
            {
                "asset_id": a.asset_id,
                "scores": a.scores.model_dump(mode="json") if a.scores else None,
                "detected_subjects": a.detected_subjects or [],
            }
            for a in assets
        ],
    }
