"""Domain database layer: programmatic MongoDB MCP client + wrappers.

Per D-019, the agent never calls MCP directly. McpToolset is owned here as a
programmatic client; domain wrappers (added in subsequent steps) call MongoDB
through it and are themselves exposed to the agent as FunctionTools.
"""

from src.db.client import MongoMCPClient

__all__ = ["MongoMCPClient"]
