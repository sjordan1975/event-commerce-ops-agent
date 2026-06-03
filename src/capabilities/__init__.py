"""Agent-facing capabilities for the event commerce ops agent.

Graph orchestration (D-024) — capabilities are wired as `FunctionNode`s and one
`LlmAgent` node inside a `google.adk.workflow.Workflow`. Chain tuples of any
length are supported by the ADK graph builder (_process_chain iterates pairwise),
so a single n-element tuple expands to n-1 edges.

Current pipeline: START → ingest_event_batch → build_event_context →
  find_similar_assets → score_assets_with_vision → prepare_queue_candidates →
  propose_review_queue → persist_review_queue → draft_campaigns_for_queue

Adapter functions (prefix `_node_*`) wrap each capability so the workflow node
writes its outputs back to `ctx.state` for downstream nodes to read. The LlmAgent
node (propose_review_queue) needs no adapter — it reads/writes state via the
instruction provider + output_key.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from google.adk.workflow import FunctionNode, START

from src.capabilities.context import build_event_context as _build_event_context
from src.capabilities.drafts import draft_campaigns_for_queue
from src.capabilities.ingest import ingest_event_batch as _ingest_event_batch
from src.capabilities.queue import (
    build_review_queue_node,
    persist_review_queue,
    prepare_queue_candidates,
)
from src.capabilities.scoring import score_assets_with_vision as _score_assets_with_vision
from src.capabilities.similarity import find_similar_assets as _find_similar_assets
from src.models import ReviewQueue
from src.sse import get_queue

WORKFLOW_NAME = "event_pipeline"


def _sse_emit(ctx: Any, event_type: str, payload: dict) -> None:
    """Fire-and-forget SSE event from a workflow node.

    Reads _sse_session_id from ctx.state. No-ops if the key is absent (unit
    tests, evals, any non-SSE invocation path).
    """
    sid = ctx.state.get("_sse_session_id")
    if not sid:
        return
    q = get_queue(sid)
    if q is not None:
        q.put_nowait({"type": event_type, "payload": payload})


async def _node_ingest_event_batch(
    ctx: Any, images: list[str], event_metadata: dict
) -> dict:
    """Workflow adapter: calls ingest_event_batch and writes outputs to state."""
    _sse_emit(ctx, "capability_started", {"capability": "ingest_event_batch"})
    result = await _ingest_event_batch(images=images, event_metadata=event_metadata)
    ctx.state["event_id"] = result["event_id"]
    ctx.state["asset_ids"] = result["asset_ids"]
    count = len(result.get("asset_ids") or [])
    _sse_emit(ctx, "capability_completed", {
        "capability": "ingest_event_batch",
        "resultSummary": f"{count} asset{'s' if count != 1 else ''} ingested",
    })
    return result


async def _node_build_event_context(ctx: Any, event_id: str) -> dict:
    """Workflow adapter: calls build_event_context and writes the narrative to state."""
    _sse_emit(ctx, "capability_started", {"capability": "build_event_context"})
    result = await _build_event_context(event_id)
    ctx.state["event_narrative"] = result
    narrative = result if isinstance(result, dict) else {}
    angle = narrative.get("narrative_angle", "")
    summary = f"Narrative built · {angle[:60]}" if angle else "Event narrative built"
    _sse_emit(ctx, "capability_completed", {
        "capability": "build_event_context",
        "resultSummary": summary,
    })
    return result


async def _node_find_similar_assets(ctx: Any, event_id: str) -> dict:
    """Workflow adapter: calls find_similar_assets and writes similarity_results to state."""
    _sse_emit(ctx, "capability_started", {"capability": "find_similar_assets"})
    result = await _find_similar_assets(event_id)
    ctx.state["similarity_results"] = result["similar"]
    count = len(result.get("similar") or [])
    _sse_emit(ctx, "capability_completed", {
        "capability": "find_similar_assets",
        "resultSummary": f"{count} similar asset{'s' if count != 1 else ''} found",
    })
    return result


async def _node_score_assets_with_vision(ctx: Any, event_id: str) -> dict:
    """Workflow adapter: calls score_assets_with_vision and writes scored_assets to state."""
    _sse_emit(ctx, "capability_started", {"capability": "score_assets_with_vision"})
    result = await _score_assets_with_vision(event_id)
    ctx.state["scored_assets"] = result["scored"]
    count = len(result.get("scored") or [])
    _sse_emit(ctx, "capability_completed", {
        "capability": "score_assets_with_vision",
        "resultSummary": f"Vision analysis complete · {count} asset{'s' if count != 1 else ''}",
    })
    return result


# Module-level FunctionNode instances — referenced by src/agent.py.build_workflow().
# All use parameter_binding='state': the coordinator's run_event_pipeline shim
# pre-populates session state with `images` and `event_metadata`; downstream nodes
# read and write via state.

ingest_event_batch_node = FunctionNode(
    func=_node_ingest_event_batch,
    name="ingest_event_batch",
    parameter_binding="state",
)

build_event_context_node = FunctionNode(
    func=_node_build_event_context,
    name="build_event_context",
    parameter_binding="state",
)

find_similar_assets_node = FunctionNode(
    func=_node_find_similar_assets,
    name="find_similar_assets",
    parameter_binding="state",
)

score_assets_with_vision_node = FunctionNode(
    func=_node_score_assets_with_vision,
    name="score_assets_with_vision",
    parameter_binding="state",
)


async def _node_prepare_queue_candidates(ctx: Any) -> dict:
    """Workflow adapter: joins similarity + scored assets, splits by cutoff into candidate pools."""
    _sse_emit(ctx, "capability_started", {"capability": "prepare_queue_candidates"})
    cutoff = float(os.environ.get("QUEUE_EXPLOITATION_SIMILARITY_CUTOFF", "0.75"))
    candidates = prepare_queue_candidates(
        similarity_results=ctx.state.get("similarity_results", []),
        scored_assets=ctx.state.get("scored_assets", []),
        event_narrative=ctx.state.get("event_narrative"),
        cutoff=cutoff,
    )
    ctx.state["queue_candidates"] = candidates
    n_exploit = len(candidates.get("exploitation", []))
    n_disc = len(candidates.get("discovery", []))
    _sse_emit(ctx, "capability_completed", {
        "capability": "prepare_queue_candidates",
        "resultSummary": f"{n_exploit} exploitation · {n_disc} discovery candidates",
    })
    # Anticipatory: the LlmAgent propose_review_queue node runs next — no hook point there.
    logger.info("propose_review_queue start  exploit=%d discovery=%d", n_exploit, n_disc)
    _sse_emit(ctx, "capability_started", {"capability": "propose_review_queue"})
    return candidates


async def _node_persist_review_queue(ctx: Any) -> dict:
    """Workflow adapter: persists per-asset queue assignments from the LLM's ReviewQueue."""
    # Retrospective: propose_review_queue (LlmAgent) just ran — emit its completion now.
    raw = ctx.state.get("review_queue")
    strategy_excerpt = ""
    queue_summary = "Queue assembled"
    if raw:
        try:
            q_obj = ReviewQueue.model_validate(raw) if isinstance(raw, dict) else ReviewQueue.model_validate_json(raw)
            total = len(q_obj.exploitation) + len(q_obj.discovery)
            queue_summary = f"{total} items staged · {len(q_obj.exploitation)} proven · {len(q_obj.discovery)} discovery"
            strategy_excerpt = q_obj.strategy_summary
        except Exception:
            pass
    logger.info("propose_review_queue done   %s", queue_summary)
    _sse_emit(ctx, "capability_completed", {
        "capability": "propose_review_queue",
        "resultSummary": queue_summary,
        "strategyExcerpt": strategy_excerpt,
    })

    _sse_emit(ctx, "capability_started", {"capability": "persist_review_queue"})
    result = await persist_review_queue(ctx)
    ctx.state["review_queue"] = result["review_queue"]
    ctx.state["membership_violations"] = result["membership_violations"]
    n = len(result.get("review_queue") or [])
    _sse_emit(ctx, "capability_completed", {
        "capability": "persist_review_queue",
        "resultSummary": f"{n} queue assignment{'s' if n != 1 else ''} persisted to Atlas",
    })
    return result


prepare_queue_candidates_node = FunctionNode(
    func=_node_prepare_queue_candidates,
    name="prepare_queue_candidates",
    parameter_binding="state",
)

# The project's first in-graph LlmAgent node (Path A, D-029). Reads state via
# the callable instruction provider; writes parsed ReviewQueue dict to state via
# output_key. No adapter needed.
propose_review_queue_node = build_review_queue_node()

persist_review_queue_node = FunctionNode(
    func=_node_persist_review_queue,
    name="persist_review_queue",
    parameter_binding="state",
)


async def _node_draft_campaigns_for_queue(ctx: Any) -> dict:
    """Workflow adapter: calls draft_campaigns_for_queue and writes outputs to state."""
    _sse_emit(ctx, "capability_started", {"capability": "draft_campaigns_for_queue"})
    event_id = ctx.state["event_id"]
    result = await draft_campaigns_for_queue(event_id)
    ctx.state["campaign_ids"] = result["campaign_ids"]
    ctx.state["approval_ids"] = result["approval_ids"]
    ctx.state["drafts"] = result["drafts"]
    n_campaigns = len(result.get("campaign_ids") or [])
    n_approvals = len(result.get("approval_ids") or [])
    _sse_emit(ctx, "capability_completed", {
        "capability": "draft_campaigns_for_queue",
        "resultSummary": f"{n_campaigns} draft{'s' if n_campaigns != 1 else ''} created · {n_approvals} pending approval",
    })
    return result


draft_campaigns_for_queue_node = FunctionNode(
    func=_node_draft_campaigns_for_queue,
    name="draft_campaigns_for_queue",
    parameter_binding="state",
)


def build_pipeline_graph() -> list:
    """Returns the edge list for the event pipeline workflow.

    A single chain-tuple expands to pairwise edges (ADK _process_chain semantics).
    Pipeline (9 nodes): START → ingest_event_batch → build_event_context →
      find_similar_assets → score_assets_with_vision → prepare_queue_candidates →
      propose_review_queue → persist_review_queue → draft_campaigns_for_queue.
    """
    return [
        (
            START,
            ingest_event_batch_node,
            build_event_context_node,
            find_similar_assets_node,
            score_assets_with_vision_node,
            prepare_queue_candidates_node,
            propose_review_queue_node,
            persist_review_queue_node,
            draft_campaigns_for_queue_node,
        ),
    ]
