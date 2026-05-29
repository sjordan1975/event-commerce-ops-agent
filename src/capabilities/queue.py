"""propose_review_queue — the one strategic decision (Step 5, D-021).

Three-node realization:
  prepare_queue_candidates  (FunctionNode) — mechanical join + similarity cutoff split
  propose_review_queue      (LlmAgent, mode='single_turn') — judgment: ordering,
                             selection, identity composition, quality gate, rationale
  persist_review_queue      (FunctionNode) — defensive Mongo write per surfaced item

The LlmAgent node is the project's first in-graph agent node (Path A, validated by
spike/adk_llm_node_queue_spike.py). All precondition checks live in prepare; the
instruction provider assumes a validated state (ADK's raising-provider semantics
are untested).
"""

import json
import os

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai import types as genai_types

from src.db.assets import save_queue_assignment
from src.errors import PreconditionError
from src.models import ReviewQueue
from src.prompt_loader import load_prompt

# ---------------------------------------------------------------------------
# Eval mock seam (T-5.8)
# ---------------------------------------------------------------------------

# Set by the Tier-1 eval conftest to short-circuit the live model call.
# Checked at callback call time (import-order-safe).
_FIXTURE_RESPONSE: dict | None = None


def _queue_model_callback(callback_context, llm_request) -> LlmResponse | None:
    """before_model_callback: returns None (live) or a canned LlmResponse (eval)."""
    if _FIXTURE_RESPONSE is None:
        return None
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=json.dumps(_FIXTURE_RESPONSE))],
        )
    )


# ---------------------------------------------------------------------------
# T-5.5: prepare_queue_candidates (pure — no I/O, no ADK ctx)
# ---------------------------------------------------------------------------

def prepare_queue_candidates(
    similarity_results: list[dict],
    scored_assets: list[dict],
    event_narrative: dict | None,
    cutoff: float,
) -> dict:
    """Join similarity results and scored assets, then split by cutoff.

    Returns {"exploitation": [...], "discovery": [...]}.
    Each candidate carries: asset_id, top_similarity, inferred_route, scores,
    detected_subjects.

    Raises PreconditionError (all missing keys in one error) if any input is absent.
    """
    missing: dict[str, str] = {}
    if not similarity_results:
        missing["similarity_results"] = "call find_similar_assets first"
    if not scored_assets:
        missing["scored_assets"] = "call score_assets_with_vision first"
    if event_narrative is None:
        missing["event_narrative"] = "call build_event_context first"
    if missing:
        event_id = (event_narrative or {}).get("event_id", "event")
        raise PreconditionError(
            capability="propose_review_queue",
            context=event_id,
            missing=missing,
        )

    # Index scored assets by asset_id for O(1) join
    scored_by_id = {a["asset_id"]: a for a in scored_assets}

    exploitation: list[dict] = []
    discovery: list[dict] = []

    for sr in similarity_results:
        asset_id = sr["asset_id"]
        neighbors = sr.get("neighbors", [])
        inferred_route = sr.get("inferred_route")

        top_similarity = max((n["similarity"] for n in neighbors), default=0.0)

        scored = scored_by_id.get(asset_id, {})
        candidate = {
            "asset_id": asset_id,
            "top_similarity": top_similarity,
            "inferred_route": inferred_route,
            "scores": scored.get("scores"),
            "detected_subjects": scored.get("detected_subjects", []),
        }

        if top_similarity >= cutoff:
            exploitation.append(candidate)
        else:
            discovery.append(candidate)

    return {"exploitation": exploitation, "discovery": discovery}


# ---------------------------------------------------------------------------
# T-5.6 / T-5.7: queue_instruction_provider
# ---------------------------------------------------------------------------

def queue_instruction_provider(ctx: ReadonlyContext) -> str:
    """Callable instruction provider for the LlmAgent node.

    Reads event_narrative and queue_candidates from ctx.state (assumes they
    are present — preconditions are prepare_queue_candidates's responsibility).
    Returns the formatted strategist prompt string verbatim (ADK does not
    re-template it, so embedded JSON braces are safe).
    """
    narrative = ctx.state["event_narrative"]
    candidates = ctx.state["queue_candidates"]

    event_id = narrative.get("event_id", "")
    narrative_angle = narrative.get("narrative_angle", "")

    # key_figures may be a list of dicts (production EventNarrative) or strings (spike)
    key_figures_raw = narrative.get("key_figures", [])
    if key_figures_raw and isinstance(key_figures_raw[0], dict):
        key_figures = ", ".join(kf["name"] for kf in key_figures_raw)
    else:
        key_figures = ", ".join(str(kf) for kf in key_figures_raw)

    exploitation_json = json.dumps(candidates.get("exploitation", []), indent=2)
    discovery_json = json.dumps(candidates.get("discovery", []), indent=2)

    return load_prompt("propose_review_queue").format(
        event_id=event_id,
        narrative_angle=narrative_angle,
        key_figures=key_figures,
        exploitation_json=exploitation_json,
        discovery_json=discovery_json,
    )


# ---------------------------------------------------------------------------
# T-5.8: build_review_queue_node
# ---------------------------------------------------------------------------

def build_review_queue_node() -> LlmAgent:
    """Constructs the propose_review_queue LlmAgent node (mode='single_turn').

    Model: GEMINI_QUEUE_MODEL (default gemini-2.5-flash — most judgment-dense node;
    flash-lite is documented as unreliable at judgment-dense decision points, D-028).
    output_schema=ReviewQueue + output_key lands the parsed dict in state.
    before_model_callback is always attached; returns None when _FIXTURE_RESPONSE
    is None (proceeds to live model), canned LlmResponse when set (Tier-1 eval).
    max_output_tokens bounds the per-item-reasoning payload (spend bound, D-029).
    """
    model = os.environ.get("GEMINI_QUEUE_MODEL", "gemini-2.5-flash")
    return LlmAgent(
        model=model,
        name="propose_review_queue",
        mode="single_turn",
        instruction=queue_instruction_provider,
        output_schema=ReviewQueue,
        output_key="review_queue",
        before_model_callback=_queue_model_callback,
        generate_content_config=genai_types.GenerateContentConfig(
            max_output_tokens=4096,
        ),
        description="Assemble the operator review queue (exploitation + discovery).",
    )


# ---------------------------------------------------------------------------
# T-5.9: persist_review_queue (defensive)
# ---------------------------------------------------------------------------

async def persist_review_queue(ctx) -> dict:
    """Persist per-asset queue assignments from the LLM's ReviewQueue output.

    Reads review_queue and queue_candidates from ctx.state. Defensive: if the
    LLM cross-assigns or invents an asset_id, records it in membership_violations
    and skips (does not raise).

    Routing invariant (D-015): exploitation items use the mechanical inferred_route
    from prepare_queue_candidates; discovery items use the LLM's chosen route.
    """
    raw = ctx.state["review_queue"]
    if isinstance(raw, str):
        queue = ReviewQueue.model_validate_json(raw)
    else:
        queue = ReviewQueue.model_validate(raw)

    candidates = ctx.state["queue_candidates"]
    exploitation_routes = {
        c["asset_id"]: c["inferred_route"]
        for c in candidates.get("exploitation", [])
    }
    discovery_ids = {c["asset_id"] for c in candidates.get("discovery", [])}

    violations: list[tuple[str, str]] = []

    for item in queue.exploitation:
        if item.asset_id not in exploitation_routes:
            violations.append(("exploitation", item.asset_id))
            continue
        await save_queue_assignment(
            item.asset_id,
            "exploitation",
            exploitation_routes[item.asset_id],  # mechanical route, D-015
            item.rank,
            item.rationale,
        )

    for item in queue.discovery:
        if item.asset_id not in discovery_ids:
            violations.append(("discovery", item.asset_id))
            continue
        await save_queue_assignment(
            item.asset_id,
            "discovery",
            item.product_route,  # LLM-chosen route for discovery
            item.rank,
            item.rationale,
        )

    return {
        "review_queue": queue.model_dump(mode="json"),
        "membership_violations": violations,
    }
