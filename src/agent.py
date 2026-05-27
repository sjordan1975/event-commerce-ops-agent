"""Agent shell: LlmAgent with versioned system prompt; tools provided by callers.

Per D-019, MongoDB MCP is *not* registered in `agent.tools`. It is used
programmatically via `src/db/client.py` by domain wrappers. The agent's tool
list contains only domain FunctionTools (and the LongRunningFunctionTool at
the HITL gate, added in Step 6).
"""

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from src.capabilities import all_function_tools
from src.prompt_loader import load_prompt

load_dotenv()

APP_NAME = "event_commerce_ops_agent"


def build_agent(extra_tools: list | None = None) -> LlmAgent:
    """Build and return the operations agent with production tools auto-wired."""
    tools = list(all_function_tools) + list(extra_tools or [])
    return LlmAgent(
        model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        name=APP_NAME,
        instruction=load_prompt("agent_system"),
        tools=tools,
    )


def build_runner(agent: LlmAgent | None = None) -> Runner:
    """Build a Runner backed by an in-memory session service."""
    if agent is None:
        agent = build_agent()
    return Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=InMemorySessionService(),
    )
