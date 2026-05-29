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
    }


def request_human_approval(
    approval_batch: dict,
    tool_context: ToolContext,
) -> dict | None:
    """Submits a batch of drafted campaigns for operator approval.

    Returns None to signal pending — the agent suspends and resumes when the
    caller posts a FunctionResponse with the operator's decision(s) per item.

    Args:
        approval_batch: dict with `event_id` and `items` (list of {campaign_id,
            asset_id, draft_summary}).
    """
    tool_context.actions.skip_summarization = True
    return None


def build_coordinator(extra_tools: list[Any] | None = None) -> LlmAgent:
    """Builds the chat-mode coordinator with workflow dispatch, clarification, and HITL."""
    tools: list[Any] = [
        FunctionTool(run_event_pipeline),
        LongRunningFunctionTool(func=request_human_approval),
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
