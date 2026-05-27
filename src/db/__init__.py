"""Domain database layer: programmatic MongoDB MCP client + wrappers.

Per D-019, the agent never calls MCP directly. McpToolset is owned here as a
programmatic client; domain wrappers (added in subsequent steps) call MongoDB
through it and are themselves exposed to the agent as FunctionTools.
"""

from src.db.client import MongoMCPClient

_client: MongoMCPClient | None = None


def get_client() -> MongoMCPClient:
    """Return the module-level lazy singleton MongoMCPClient."""
    global _client
    if _client is None:
        _client = MongoMCPClient()
    return _client


__all__ = ["MongoMCPClient", "get_client"]
