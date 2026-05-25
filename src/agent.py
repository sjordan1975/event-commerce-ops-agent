"""Agent shell: LlmAgent wired with McpToolset and versioned system prompt."""

import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters

from src.prompt_loader import load_prompt

load_dotenv()

APP_NAME = "event_commerce_ops_agent"


def _mcp_toolset() -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mongodb-mcp-server@latest"],
                env={
                    "MDB_MCP_CONNECTION_STRING": os.environ["MONGODB_URI"],
                    "MDB_MCP_API_CLIENT_ID": os.environ.get("MDB_MCP_API_CLIENT_ID", ""),
                    "MDB_MCP_API_CLIENT_SECRET": os.environ.get("MDB_MCP_API_CLIENT_SECRET", ""),
                },
            )
        )
    )


def build_agent(extra_tools: list | None = None) -> LlmAgent:
    """Build and return the operations agent with MCP toolset wired."""
    tools: list = [_mcp_toolset()]
    if extra_tools:
        tools.extend(extra_tools)

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
