"""Agent-facing capabilities for the event commerce ops agent.

Graph orchestration (D-024) — capabilities are wired as `FunctionNode`s inside a
`google.adk.workflow.Workflow`. Chain tuples of any length are supported by the
ADK graph builder (_process_chain iterates pairwise), so a single n-element tuple
expands to n-1 edges.

Current pipeline: START → ingest_event_batch → build_event_context → find_similar_assets

Future steps extend the graph:
  Step 4 → adds `score_assets_with_vision` node
  Step 5 → adds `propose_review_queue` (LlmAgent node, mode='single_turn')
  Step 6 → adds `draft_campaigns_for_queue` node

Adapter functions (prefix `_node_*`) wrap each capability so the workflow node
writes its outputs back to `ctx.state` for downstream nodes to read.
"""

from typing import Any

from google.adk.workflow import FunctionNode, START

from src.capabilities.context import build_event_context as _build_event_context
from src.capabilities.ingest import ingest_event_batch as _ingest_event_batch
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


def build_pipeline_graph() -> list:
    """Returns the edge list for the event pipeline workflow.

    A single chain-tuple expands to pairwise edges (ADK _process_chain semantics).
    Pipeline: START → ingest_event_batch → build_event_context → find_similar_assets.
    """
    return [
        (START, ingest_event_batch_node, build_event_context_node, find_similar_assets_node),
    ]
