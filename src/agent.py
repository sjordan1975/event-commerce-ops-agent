"""Coordinator + Workflow agent shell (D-024 graph-orchestrated architecture).

The agent is a chat-mode `LlmAgent` coordinator that:
  - owns the operator conversation
  - delegates clarification to a `mode='task'` sub-agent
  - dispatches deterministic processing to a `google.adk.workflow.Workflow`
  - handles human approval via `LongRunningFunctionTool`

The Workflow contains FunctionNodes for the deterministic capabilities; the one
strategic decision node (`propose_review_queue`) is added inside the Workflow
in Step 5 as an `LlmAgent(mode='single_turn')` node.

Model pinning (per spike findings):
  - Coordinator: gemini-2.5-flash (flash-lite hallucinates instead of delegating)
  - Workflow nodes: gemini-2.5-flash-lite (default GEMINI_MODEL)

Per D-019, MongoDB MCP is not registered on any agent's tools. It is used
programmatically via `src/db/client.py` by the capability functions.
"""

import os
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.tool_context import ToolContext
from google.adk.workflow import Workflow
from google.genai import types

from src.capabilities import WORKFLOW_NAME, build_pipeline_graph
from src.images import list_images as _list_images_impl
from src.capabilities.drafts import draft_campaigns_for_queue
from src.capabilities.execution import execute_approved_campaigns
from src.capabilities.outcomes import record_outcomes
from src.db.approvals import get_pending_approvals, record_approval_decision
from src.db.assets import get_assets_by_ids
from src.db.campaigns import get_campaigns_by_ids
from src.models import ApprovalDecision
from src.prompt_loader import load_prompt

load_dotenv()

APP_NAME = "event_commerce_ops_agent"
COORDINATOR_NAME = "event_commerce_ops_coordinator"
CLARIFICATION_NAME = "clarify_event_metadata"


def _coordinator_model() -> str:
    return os.environ.get("GEMINI_COORDINATOR_MODEL", "gemini-2.5-flash")


def _workflow_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")


def build_clarification_agent() -> LlmAgent:
    """The task-mode sub-agent for bidirectional clarification."""
    return LlmAgent(
        model=_coordinator_model(),
        name=CLARIFICATION_NAME,
        mode="task",
        description=(
            "REQUIRED when the operator's batch message lacks a clear value for "
            "outcome_type (or another required event_metadata field). Engages "
            "the operator in a multi-turn exchange to ask for the missing value "
            "and returns it. Call this instead of guessing."
        ),
        instruction=load_prompt("clarification_system"),
    )


def build_workflow() -> Workflow:
    """Constructs the event pipeline workflow graph."""
    return Workflow(name=WORKFLOW_NAME, edges=build_pipeline_graph())


async def run_event_pipeline(
    images: list[str],
    event_metadata: dict,
    tool_context: ToolContext,
) -> dict:
    """Dispatches the deterministic event pipeline for a complete batch.

    Use this once event_metadata is complete and unambiguous (all required
    fields present: name, home_team, away_team, final_score, start_date,
    outcome_type). The pipeline runs ingestion -> context -> [future: similarity,
    scoring, queue assembly, drafts] and returns the final state.

    Args:
        images: list of image paths/urls to ingest.
        event_metadata: dict with name, home_team, away_team, final_score,
            start_date (ISO 8601 UTC), outcome_type.

    Returns:
        Dict with event_id, asset_ids, event_narrative.
    """
    tool_context.actions.skip_summarization = False

    workflow = build_workflow()
    sub_session_service = InMemorySessionService()
    sub_session = await sub_session_service.create_session(
        app_name=WORKFLOW_NAME,
        user_id="coordinator",
        state={"images": images, "event_metadata": event_metadata},
    )
    sub_runner = Runner(
        app_name=WORKFLOW_NAME,
        node=workflow,
        session_service=sub_session_service,
    )

    trigger = types.Content(role="user", parts=[types.Part(text="run pipeline")])
    async for _event in sub_runner.run_async(
        user_id="coordinator",
        session_id=sub_session.id,
        new_message=trigger,
    ):
        pass

    final_session = await sub_session_service.get_session(
        app_name=WORKFLOW_NAME,
        user_id="coordinator",
        session_id=sub_session.id,
    )
    state = dict(final_session.state) if final_session else {}
    return {
        "event_id": state.get("event_id"),
        "asset_ids": state.get("asset_ids"),
        "event_narrative": state.get("event_narrative"),
        "similarity_results": state.get("similarity_results"),
        "scored_assets": state.get("scored_assets"),
        "queue_candidates": state.get("queue_candidates"),
        "review_queue": state.get("review_queue"),
        "membership_violations": state.get("membership_violations"),
        "campaign_ids": state.get("campaign_ids"),
        "approval_ids": state.get("approval_ids"),
        "drafts": state.get("drafts"),
    }


async def request_human_approval(
    event_id: str,
    tool_context: ToolContext,
) -> dict | None:
    """Reads pending approval batch and suspends waiting for operator decisions.

    Builds a display batch grouped by queue half (exploitation / exploration)
    with each item keyed by approval_id. Stores the batch in tool_context.state
    so the approval surface can read it via get_pending_approvals(event_id).
    Returns None to suspend; no decision writes are made here.
    Decisions are persisted by apply_approval_decisions on resume.

    Note: returns None (verified suspension pattern from adk_hitl_test.py spike).
    The surface fetches the batch independently via get_pending_approvals(event_id)
    since it already has event_id. Batch is also stored in state["pending_batch"]
    for debugging / operator UI.

    Args:
        event_id: the event whose pending approvals to fetch.

    Returns:
        None — suspends until a decisions FunctionResponse arrives.
    """
    tool_context.actions.skip_summarization = True

    pending = await get_pending_approvals(event_id)

    campaign_ids = [a.campaign_id for a in pending]
    asset_ids = [a.asset_id for a in pending]

    campaigns = await get_campaigns_by_ids(campaign_ids)
    assets = await get_assets_by_ids(asset_ids)

    campaign_by_id = {c.campaign_id: c for c in campaigns}
    asset_by_id = {a.asset_id: a for a in assets}

    exploitation: list[dict] = []
    exploration: list[dict] = []

    for approval in pending:
        campaign = campaign_by_id.get(approval.campaign_id)
        asset = asset_by_id.get(approval.asset_id)
        if not campaign or not asset:
            continue

        item: dict = {
            "approval_id": approval.approval_id,
            "campaign_id": campaign.campaign_id,
            "asset_id": asset.asset_id,
            "content_url": asset.content_url,
            "queue_rank": asset.queue_rank,
            "queue_rationale": asset.queue_rationale,
            "product_route": asset.product_route,
            "headline": campaign.generated_copy.headline,
            "caption": campaign.generated_copy.caption,
            "hashtags": campaign.generated_copy.hashtags,
            "timing_recommendation": campaign.timing_recommendation,
        }

        if asset.queue_type == "exploitation":
            exploitation.append(item)
        else:
            exploration.append(item)

    # Store for operator surface / debugging; surface fetches independently by event_id.
    tool_context.state["pending_batch"] = {
        "event_id": event_id,
        "exploitation": exploitation,
        "exploration": exploration,
    }

    return None  # suspend; FunctionResponse delivers decisions to the coordinator LLM


async def apply_approval_decisions(decisions: list[dict], tool_context: ToolContext) -> dict:
    """Persists per-item operator decisions to MongoDB. The only place decisions hit Mongo.

    Validates each entry as ApprovalDecision (boundary extra='forbid'), then
    records each decision and returns a summary bucket.

    Args:
        decisions: list of {approval_id, decision, reviewer_notes?}.

    Returns:
        {"approved": [campaign_id...], "rejected": [campaign_id...],
         "edit_requested": [{approval_id, campaign_id, asset_id, reviewer_notes}...]}
    """
    approved: list[str] = []
    rejected: list[str] = []
    edit_requested: list[dict] = []

    for raw in decisions:
        d = ApprovalDecision(**raw)  # raises ValidationError on bad input before any write
        await record_approval_decision(d.approval_id, d)

        # Resolve campaign_id and asset_id from the approval doc (fetched inside record_approval_decision,
        # but not returned — get them from the raw dict which caller constructs from the FunctionResponse).
        # The decisions list carries approval_id; we infer campaign_id below from the bucketing result.
        # Since we only have approval_id here, we return it per bucket for the LLM to act on.
        if d.decision == "approved":
            approved.append(d.approval_id)
        elif d.decision == "rejected":
            rejected.append(d.approval_id)
        else:
            edit_requested.append({
                "approval_id": d.approval_id,
                "reviewer_notes": d.reviewer_notes,
            })

    return {"approved": approved, "rejected": rejected, "edit_requested": edit_requested}


MAX_REDRAFT_CYCLES = int(os.environ.get("MAX_REDRAFT_CYCLES", "3"))

# ADK iteration backstop (per safety-measures.md Gap 1). The load-bearing bound is
# MAX_REDRAFT_CYCLES (3); this 30-call cap is the catch-all framework backstop.
# Callers pass RunConfig(max_llm_calls=COORDINATOR_MAX_LLM_CALLS) to run_async.
COORDINATOR_MAX_LLM_CALLS = 30


async def redraft_campaigns(event_id: str, tool_context: ToolContext) -> dict:
    """Shim: increment the redraft cap counter and call draft_campaigns_for_queue in redraft mode.

    Refuses past MAX_REDRAFT_CYCLES (tool-level hard cap, defense-in-depth against
    the coordinator's prompt-level 3-cycle rule). The cap counter survives suspend/resume
    because it lives in tool_context.state (session state).

    Args:
        event_id: the event whose edit_requested campaigns to redraft.

    Returns:
        The draft result dict, or {"status": "cap_reached", "message": ...} if capped.
    """
    n = tool_context.state.get("redraft_cycles", 0) + 1
    if n > MAX_REDRAFT_CYCLES:
        return {
            "status": "cap_reached",
            "message": f"escalate to operator; revision limit hit ({MAX_REDRAFT_CYCLES} cycles)",
        }
    tool_context.state["redraft_cycles"] = n
    return await draft_campaigns_for_queue(event_id)


def list_images(path: str) -> dict:
    """List image files available for batch ingestion.

    Accepts a local directory path (e.g. /tmp/wc-final/) or a GCS URI
    (e.g. gs://fieldhouse-demo/wc-final/). Returns {"files": [...], "count": N}
    on success, or {"error": "...", "files": [], "count": 0} if the path is
    inaccessible. Call this before run_event_pipeline to enumerate the batch.
    """
    return _list_images_impl(path)


def build_coordinator(extra_tools: list[Any] | None = None) -> LlmAgent:
    """Builds the chat-mode coordinator with workflow dispatch, clarification, and HITL."""
    tools: list[Any] = [
        FunctionTool(list_images),
        FunctionTool(run_event_pipeline),
        LongRunningFunctionTool(func=request_human_approval),
        FunctionTool(apply_approval_decisions),
        FunctionTool(redraft_campaigns),
        FunctionTool(execute_approved_campaigns),
        FunctionTool(record_outcomes),
    ]
    if extra_tools:
        tools.extend(extra_tools)

    return LlmAgent(
        model=_coordinator_model(),
        name=COORDINATOR_NAME,
        mode="chat",
        instruction=load_prompt("coordinator_system"),
        tools=tools,
        sub_agents=[build_clarification_agent()],
    )


# Backwards-compatible alias for existing eval scaffolding. Marked for removal
# once tests/evals/conftest.py is updated to the new name.
def build_agent(extra_tools: list[Any] | None = None) -> LlmAgent:
    """Deprecated alias — use build_coordinator. Kept for eval scaffolding compatibility."""
    return build_coordinator(extra_tools=extra_tools)


def build_runner(agent: LlmAgent | None = None) -> Runner:
    """Build a Runner backed by an in-memory session service."""
    if agent is None:
        agent = build_coordinator()
    return Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=InMemorySessionService(),
    )
