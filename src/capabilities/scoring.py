"""score_assets_with_vision — agent-facing capability for Step 4.

STUB — real implementation lands in Step 4 (Gemini Vision scoring across 5
dimensions: emotional_score, social_score, technical_quality, narrative_fit,
brand_safety). Until then, calling this raises NotImplementedError.
"""


async def score_assets_with_vision(event_id: str) -> dict:
    """Scores each asset along five dimensions via Gemini Vision.

    Args:
        event_id: id of the event whose assets to score.

    Returns:
        {"event_id": str, "scored_asset_ids": list[str]} once persisted.
    """
    raise NotImplementedError(
        "score_assets_with_vision is implemented in Step 4 (Gemini Vision "
        "5-dimensional scoring). This stub exists so the capability surface is "
        "reservable and importable now."
    )
