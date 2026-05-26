"""Programmatic MongoDB MCP client (D-019).

Owns a single McpToolset instance and exposes a `call(tool_name, args)` API
that wrappers in `src/db/` use to talk to MongoDB. McpToolset is *not*
registered in `agent.tools` — that's the by-construction enforcement of
D-019, verified by the `test_agent_does_not_expose_mcp_directly` regression
test and by spike/adk_mcp_programmatic.py.
"""

import os

from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters


class MongoMCPClient:
    """Programmatic MongoDB MCP client. Single instance, shared by all wrappers."""

    def __init__(self) -> None:
        self._toolset = McpToolset(
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
        self._tools_by_name: dict[str, object] | None = None

    async def _ensure_tools(self) -> None:
        if self._tools_by_name is None:
            tools = await self._toolset.get_tools()
            self._tools_by_name = {t.name: t for t in tools}

    async def call(self, tool_name: str, args: dict) -> dict:
        """Invoke an MCP tool by name with structured args. Returns the raw envelope.

        Response shape: {"content": [{"type": "text", "text": "..."}, ...]}.
        Wrappers parse the envelope as needed.
        """
        await self._ensure_tools()
        assert self._tools_by_name is not None
        if tool_name not in self._tools_by_name:
            raise KeyError(
                f"MCP tool {tool_name!r} not available. "
                f"Known tools: {sorted(self._tools_by_name)[:10]}..."
            )
        tool = self._tools_by_name[tool_name]
        return await tool.run_async(args=args, tool_context=None)  # type: ignore[attr-defined]

    async def close(self) -> None:
        await self._toolset.close()
