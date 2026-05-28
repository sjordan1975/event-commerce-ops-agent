"""draft_campaigns_for_queue — Step 6.

STUB — real implementation lands in Step 6 (LLM-driven copy generation using
the EventNarrative from Step 2 as substrate). Creates campaign documents +
approval records per queue item. Until then, calling this raises NotImplementedError.
"""


async def draft_campaigns_for_queue(queue: dict, operator_notes: dict | None = None) -> dict:
    """Generates campaign copy for each queued asset using the event narrative.

    Args:
        queue: the output of propose_review_queue — ranked items with per-item
            reasoning.
        operator_notes: optional per-item notes from a prior approval cycle
            (redraft case). When present, the LLM is conditioned to incorporate them.

    Returns:
        {"campaign_ids": list[str], "approval_ids": list[str]} once persisted.
    """
    raise NotImplementedError(
        "draft_campaigns_for_queue is implemented in Step 6 (LLM-driven copy "
        "generation grounded in the EventNarrative substrate). This stub exists "
        "so the capability surface is reservable and importable now."
    )
