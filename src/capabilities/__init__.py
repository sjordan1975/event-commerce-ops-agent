"""Agent-facing capabilities for the event commerce ops agent."""

from google.adk.tools import FunctionTool

from src.capabilities.context import build_event_context
from src.capabilities.ingest import ingest_event_batch

all_function_tools: list[FunctionTool] = [
    FunctionTool(ingest_event_batch),
    FunctionTool(build_event_context),
]
