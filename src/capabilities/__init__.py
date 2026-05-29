"""Agent-facing capabilities for the event commerce ops agent.

Graph orchestration (D-024) — capabilities are wired as `FunctionNode`s and one
`LlmAgent` node inside a `google.adk.workflow.Workflow`. Chain tuples of any
length are supported by the ADK graph builder (_process_chain iterates pairwise),
so a single n-element tuple expands to n-1 edges.

Current pipeline: START → ingest_event_batch → build_event_context →
  find_similar_assets → score_assets_with_vision → prepare_queue_candidates →
  propose_review_queue → persist_review_queue

Adapter functions (prefix `_node_*`) wrap each capability so the workflow node
writes its outputs back to `ctx.state` for downstream nodes to read. The LlmAgent
node (propose_review_queue) needs no adapter — it reads/writes state via the
instruction provider + output_key.
"""

import os
from typing import Any

from google.adk.workflow import FunctionNode, START

from src.capabilities.context import build_event_context as _build_event_context
from src.capabilities.ingest import ingest_event_batch as _ingest_event_batch
from src.capabilities.queue import (
    build_review_queue_node,
    persist_review_queue,
    prepare_queue_candidates,
)
from src.capabilities.scoring import score_assets_with_vision as _score_assets_with_vision
from src.capabilities.similarity import find_similar_assets as _find_similar_assets

WORKFLOW_NAME = "event_pipeline"


async def _node_ingest_event_batch(
    ctx: Any, images: list[str], event_metadata: dict
) -> dict:
    """Workflow adapter: calls ingest_event_batch and writes outputs to state.

    Reads `images` and `event_metadata` from session state (pre-populated by the
    coordinator's run_event_pipeline shim). Writes `event_id` and `asset_ids`
    back to state for downstream nodes.
    """
    result = await _ingest_event_batch(images=images, event_metadata=event_metadata)
    ctx.state["event_id"] = result["event_id"]
    ctx.state["asset_ids"] = result["asset_ids"]
    return result


async def _node_build_event_context(ctx: Any, event_id: str) -> dict:
    """Workflow adapter: calls build_event_context and writes the narrative to state.

    Reads `event_id` from state (written by the upstream ingest node).
    """
    result = await _build_event_context(event_id)
    ctx.state["event_narrative"] = result
    return result


async def _node_find_similar_assets(ctx: Any, event_id: str) -> dict:
    """Workflow adapter: calls find_similar_assets and writes similarity_results to state.

    Reads `event_id` from state (written by the upstream ingest node).
    """
    result = await _find_similar_assets(event_id)
    ctx.state["similarity_results"] = result["similar"]
    return result


async def _node_score_assets_with_vision(ctx: Any, event_id: str) -> dict:
    """Workflow adapter: calls score_assets_with_vision and writes scored_assets to state.

    Reads `event_id` from state (written by the upstream ingest node).
    """
    result = await _score_assets_with_vision(event_id)
    ctx.state["scored_assets"] = result["scored"]
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
    """Workflow adapter: joins similarity + scored assets, splits by cutoff into candidate pools.

    Reads similarity_results, scored_assets, event_narrative from state.
    Writes queue_candidates = {"exploitation": [...], "discovery": [...]} to state.
    """
    cutoff = float(os.environ.get("QUEUE_EXPLOITATION_SIMILARITY_CUTOFF", "0.75"))
    candidates = prepare_queue_candidates(
        similarity_results=ctx.state.get("similarity_results", []),
        scored_assets=ctx.state.get("scored_assets", []),
        event_narrative=ctx.state.get("event_narrative"),
        cutoff=cutoff,
    )
    ctx.state["queue_candidates"] = candidates
    return candidates


async def _node_persist_review_queue(ctx: Any) -> dict:
    """Workflow adapter: persists per-asset queue assignments from the LLM's ReviewQueue.

    Reads review_queue and queue_candidates from state (written by upstream nodes).
    Writes review_queue and membership_violations back to state.
    """
    result = await persist_review_queue(ctx)
    ctx.state["review_queue"] = result["review_queue"]
    ctx.state["membership_violations"] = result["membership_violations"]
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


def build_pipeline_graph() -> list:
    """Returns the edge list for the event pipeline workflow.

    A single chain-tuple expands to pairwise edges (ADK _process_chain semantics).
    Pipeline (8 nodes): START → ingest_event_batch → build_event_context →
      find_similar_assets → score_assets_with_vision → prepare_queue_candidates →
      propose_review_queue → persist_review_queue.
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
        ),
    ]
