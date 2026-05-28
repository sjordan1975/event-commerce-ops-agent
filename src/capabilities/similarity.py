"""find_similar_assets — agent-facing capability for Step 3.

STUB — real implementation lands in Step 3 (vector embedding + Atlas Vector Search
against the `assets` collection). Until then, calling this raises NotImplementedError.

The wired-in-the-workflow form takes `event_id` from upstream state (the
`ingest_event_batch` node writes it) and writes its results back to state for
`propose_review_queue` to consume.
"""


async def find_similar_assets(event_id: str) -> dict:
    """Finds past assets similar to those in this event via vector search.

    Args:
        event_id: id of the event whose assets to embed and search against.

    Returns:
        {"event_id": str, "similar": list[dict]} where each dict carries the
        target asset_id + a ranked list of past_asset_ids with similarity scores.
    """
    raise NotImplementedError(
        "find_similar_assets is implemented in Step 3 (vector embedding via "
        "gemini-embedding-2 + MongoDB Atlas Vector Search). This stub exists "
        "so the capability surface is reservable and importable now."
    )
