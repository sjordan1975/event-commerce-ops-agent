"""Minimal Phase-B backend: persistent MCP session behind a REST boundary (D-033/D-035).

Walking skeleton — the thinnest real slice of browser -> REST -> persistent MCP
session -> Atlas. The MongoDB MCP connection is established once at startup (not
per request) and reused; requests fail fast if it is not ready.

Run from the repo root:
    MONGODB_URI=... uvicorn src.api.server:app --port 8000
"""

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

# Default to the vendored MCP server binary (direct exec, no npx/registry) unless the
# environment overrides it. Set before importing get_client so the singleton picks it up.
_VENDORED_BIN = Path(__file__).parent / "node_modules" / ".bin" / "mongodb-mcp-server"
os.environ.setdefault("MONGODB_MCP_COMMAND", str(_VENDORED_BIN))

from src.db import get_client  # noqa: E402 — must follow the MONGODB_MCP_COMMAND default

_HERE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pay the MCP cold start once, at boot. A failure is recorded, not raised, so the
    # app still serves /health (degraded) instead of crash-looping.
    app.state.mcp_error = None
    try:
        await get_client().warm(timeout=45)
    except Exception as exc:  # noqa: BLE001 — boot-time health signal, surfaced via /health
        app.state.mcp_error = f"{type(exc).__name__}: {exc}"
    yield
    await get_client().close()


app = FastAPI(title="Event Commerce Ops — MCP skeleton", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """MCP lifecycle health — full signal set consumed by the UI McpHealthBadge."""
    client = get_client()
    return {
        "status":               client.status,
        "mcp_ready":            client.ready,
        "tools_discovered":     client.tools_discovered,
        "last_successful_call": client.last_successful_call_iso,
        "reconnect_attempts":   client.reconnect_attempts,
        "server_version":       client.server_version,
        "error":                app.state.mcp_error,
    }


@app.get("/api/asset-count")
async def asset_count():
    """Count assets in Atlas via the persistent MCP session. Expected: 40."""
    client = get_client()
    if not client.ready:
        return JSONResponse({"error": "data service unavailable"}, status_code=503)
    envelope = await client.call("count", {"database": "event_commerce", "collection": "assets"})
    text = "".join(part.get("text", "") for part in envelope.get("content", []))
    match = re.search(r"(\d+)", text)
    return {"count": int(match.group(1)) if match else None, "raw": text.strip()}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_HERE / "index.html")
