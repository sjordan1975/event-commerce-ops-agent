"""Programmatic MongoDB MCP client (D-019).

Owns a single McpToolset instance and exposes a `call(tool_name, args)` API
that wrappers in `src/db/` use to talk to MongoDB. McpToolset is *not*
registered in `agent.tools` — that's the by-construction enforcement of
D-019, verified by the `test_agent_does_not_expose_mcp_directly` regression
test and by spike/adk_mcp_programmatic.py.
"""

import asyncio
import os
from datetime import datetime, timezone

from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters


class MongoMCPClient:
    """Programmatic MongoDB MCP client. Single instance, shared by all wrappers."""

    def __init__(self) -> None:
        # Launch mechanism (D-035): prefer a pre-installed/vendored server binary via
        # MONGODB_MCP_COMMAND (e.g. src/api/node_modules/.bin/mongodb-mcp-server) — a
        # direct exec with no npx and no registry round-trip. This is the reliable path
        # for the FastAPI backend and Cloud Run. Fallback is npx, pinned + --prefer-offline:
        # never @latest (or a bare range), which forces a registry resolve on every cold
        # start that blocks the event loop and hangs in network-restricted environments.
        # Override the fallback version via MONGODB_MCP_VERSION. Full lifecycle treatment
        # (eager connect, fail-fast, reconnect, health) lives in the src/api connection
        # manager — see docs/plans/mcp-connection-lifecycle.md.
        mcp_command = os.environ.get("MONGODB_MCP_COMMAND")
        if mcp_command:
            command, args = mcp_command, []
        else:
            mcp_version = os.environ.get("MONGODB_MCP_VERSION", "1.11.0")
            command = "npx"
            args = ["-y", "--prefer-offline", f"mongodb-mcp-server@{mcp_version}"]
        self._toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=command,
                    args=args,
                    env={
                        "MDB_MCP_CONNECTION_STRING": os.environ["MONGODB_URI"],
                        "MDB_MCP_API_CLIENT_ID": os.environ.get("MDB_MCP_API_CLIENT_ID", ""),
                        "MDB_MCP_API_CLIENT_SECRET": os.environ.get("MDB_MCP_API_CLIENT_SECRET", ""),
                    },
                )
            )
        )
        self._tools_by_name: dict[str, object] | None = None
        self._ready = False
        self._last_successful_call: datetime | None = None
        self._reconnect_attempts: int = 0

    @property
    def ready(self) -> bool:
        """True once the MCP session is established and tool discovery is cached."""
        return self._ready

    @property
    def status(self) -> str:
        return "connected" if self._ready else "unavailable"

    @property
    def tools_discovered(self) -> int:
        return len(self._tools_by_name) if self._tools_by_name else 0

    @property
    def server_version(self) -> str:
        return os.environ.get("MONGODB_MCP_VERSION", "1.11.0")

    @property
    def last_successful_call_iso(self) -> str | None:
        return self._last_successful_call.isoformat() if self._last_successful_call else None

    @property
    def reconnect_attempts(self) -> int:
        return self._reconnect_attempts

    async def warm(self, timeout: float = 30.0) -> None:
        """Eagerly establish the MCP session + cache tool discovery at startup.

        Call once at boot (e.g. a FastAPI lifespan handler) so the cold start is paid
        then, not on the first user request. Bounds the *async* init by `timeout` so a
        slow/unavailable MCP server surfaces as a startup failure the caller can gate on,
        rather than a hung first request. (A wedged subprocess spawn that blocks the loop
        is mitigated by --prefer-offline and fully handled by the D-035 manager.)
        """
        await asyncio.wait_for(self._ensure_tools(), timeout=timeout)

    async def _ensure_tools(self) -> None:
        if self._tools_by_name is None:
            tools = await self._toolset.get_tools()
            self._tools_by_name = {t.name: t for t in tools}
            self._ready = True

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
        result = await tool.run_async(args=args, tool_context=None)  # type: ignore[attr-defined]
        self._last_successful_call = datetime.now(timezone.utc)
        return result

    async def close(self) -> None:
        await self._toolset.close()
        self._ready = False
