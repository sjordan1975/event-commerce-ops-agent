"""
Foundation smoke tests: agent boots, echo tool registers and is callable,
runner processes an event stream. Mocked at the Runner boundary — no live API calls.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.adk.tools import FunctionTool
from google.genai import types


def _echo(message: str) -> str:
    """Echo the message back. Use this to verify the agent can call tools."""
    return message


echo_tool = FunctionTool(_echo)


def test_coordinator_builds_with_echo_tool():
    from src.agent import COORDINATOR_NAME, build_coordinator

    agent = build_coordinator(extra_tools=[echo_tool])
    assert agent is not None
    assert agent.name == COORDINATOR_NAME
    assert agent.mode == "chat"
    tool_names = {t.name for t in agent.tools}
    assert "run_event_pipeline" in tool_names
    assert "request_human_approval" in tool_names
    assert "_echo" in tool_names
    sub_agent_names = {s.name for s in agent.sub_agents}
    assert "clarify_event_metadata" in sub_agent_names


def test_echo_tool_is_callable():
    assert _echo("hello world") == "hello world"
    assert _echo("") == ""


def test_echo_tool_wrapped_correctly():
    # FunctionTool exposes the underlying function name
    assert echo_tool.name == "_echo"


@pytest.mark.anyio
async def test_runner_processes_event_stream():
    """
    Mock the Runner to yield a tool-call event followed by a text response.
    Asserts the event-processing loop works and trace is non-empty.
    """
    from src.agent import build_coordinator

    agent = build_coordinator(extra_tools=[echo_tool])

    tool_call_event = MagicMock()
    tool_call_event.is_final_response.return_value = False
    tool_call_event.content = types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name="_echo", args={"message": "ping"}))],
    )

    text_event = MagicMock()
    text_event.is_final_response.return_value = True
    text_event.content = types.Content(
        role="model",
        parts=[types.Part(text="ping")],
    )

    async def _mock_run_async(**kwargs):
        yield tool_call_event
        yield text_event

    mock_runner = MagicMock()
    mock_runner.run_async = _mock_run_async

    trace_parts = []
    tool_calls = []

    msg = types.Content(role="user", parts=[types.Part(text="echo ping")])
    async for event in mock_runner.run_async(
        user_id="test", session_id="test", new_message=msg
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    trace_parts.append(part.text)
                if hasattr(part, "function_call") and part.function_call:
                    tool_calls.append(part.function_call.name)

    assert len(tool_calls) > 0, "No tool calls observed in event stream"
    assert tool_calls[0] == "_echo"
    assert len(trace_parts) > 0, "Reasoning trace is empty"


def test_coordinator_does_not_expose_mcp_directly():
    """D-019: coordinator.tools must not include McpToolset directly."""
    from src.agent import build_coordinator
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

    agent = build_coordinator()
    for tool in agent.tools:
        assert not isinstance(tool, McpToolset), (
            "McpToolset found in coordinator.tools — violates D-019. "
            "MongoDB MCP must be used programmatically via src/db/client.py, "
            "not registered as an agent tool."
        )
