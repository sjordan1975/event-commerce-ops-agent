"""propose_review_queue — the one strategic decision (Step 5).

STUB — real implementation lands in Step 5 as an LlmAgent(mode='single_turn')
node inside the workflow. The agent will read upstream state (event_narrative,
similarity results, scores) and emit a ranked queue with exploitation ordering,
exploration selection, and per-item reasoning per D-021.

Until Step 5, calling the function-form raises NotImplementedError. The agent
factory is also stubbed — it returns a placeholder LlmAgent that documents the
intent but is not wired into the workflow yet.
"""


async def propose_review_queue(event_id: str) -> dict:
    """Assembles a ranked operator review queue for an event.

    The strategic decision per D-021 — composes exploitation + exploration with
    per-item reasoning. Implemented in Step 5 as an LlmAgent node, not a function.
    """
    raise NotImplementedError(
        "propose_review_queue is the strategic decision node — implemented in "
        "Step 5 as an LlmAgent(mode='single_turn') node inside the workflow, "
        "not as a plain function. See D-021 + strategic-agent-reframe.md."
    )
