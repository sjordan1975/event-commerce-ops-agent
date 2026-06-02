"""Phase-B backend: persistent MCP session + SSE pipeline wire-up (D-033/D-035).

Endpoints:
  GET  /health                    — MCP lifecycle health (McpHealthBadge)
  GET  /api/asset-count           — count assets in Atlas
  POST /api/pipeline/run          — start coordinator Turn 1; returns SSE stream
  POST /api/pipeline/decisions    — submit HITL decisions; returns SSE stream (Turn 2)
  GET  /api/mockup/{asset_id}     — serve Gemini-generated preview mockup bytes

Run from the repo root:
    .venv/bin/python3 -m uvicorn src.api.server:app --port 8000
"""

import asyncio
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

load_dotenv()

# Default to the vendored MCP server binary (direct exec, no npx/registry) unless the
# environment overrides it. Set before importing get_client so the singleton picks it up.
_VENDORED_BIN = Path(__file__).parent / "node_modules" / ".bin" / "mongodb-mcp-server"
os.environ.setdefault("MONGODB_MCP_COMMAND", str(_VENDORED_BIN))

from src.db import get_client  # noqa: E402 — must follow the MONGODB_MCP_COMMAND default
from src.agent import APP_NAME, COORDINATOR_NAME, build_coordinator  # noqa: E402
from src.api.session_store import get as get_session, store as store_session  # noqa: E402
from src.mockup_store import get_mockup  # noqa: E402
from src.sse import close_queue, create_queue  # noqa: E402

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

_HERE = Path(__file__).parent

# Session services: one per SSE session (not shared — each coordinator needs its own).
_session_services: dict[str, InMemorySessionService] = {}

_OPERATOR_USER_ID = "operator"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mcp_error = None
    try:
        await get_client().warm(timeout=45)
    except Exception as exc:  # noqa: BLE001
        app.state.mcp_error = f"{type(exc).__name__}: {exc}"
    yield
    await get_client().close()


app = FastAPI(title="Event Commerce Ops — SSE pipeline", lifespan=lifespan)

# Allow the Next.js dev server (and any origin during demo) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------------

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
    """Count assets in Atlas via the persistent MCP session."""
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


# ---------------------------------------------------------------------------
# Mockup image endpoint (Turn 2 preview mode)
# ---------------------------------------------------------------------------

@app.get("/api/mockup/{asset_id}")
async def serve_mockup(asset_id: str) -> Response:
    """Return Gemini-generated preview mockup bytes for asset_id."""
    img_bytes = get_mockup(asset_id)
    if img_bytes is None:
        raise HTTPException(status_code=404, detail="mockup not found")
    return Response(content=img_bytes, media_type="image/png")


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _drain_queue(session_id: str, q: "asyncio.Queue[dict | None]"):
    """Async generator: yields SSE lines from the queue until the None sentinel."""
    yield _sse_event({"type": "session_started", "payload": {"session_id": session_id}})
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=300)
            except asyncio.TimeoutError:
                yield _sse_event({"type": "error", "payload": {"message": "coordinator timeout"}})
                break
            if event is None:
                break
            yield _sse_event(event)
    finally:
        close_queue(session_id)


async def _run_coordinator_turn(
    runner: Runner,
    session_id: str,
    adk_session_id: str,
    message: str,
    q: "asyncio.Queue[dict | None]",
) -> None:
    """Background task: drive one coordinator turn and put the sentinel when done."""
    trigger = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
    try:
        async for event in runner.run_async(
            user_id=_OPERATOR_USER_ID,
            session_id=adk_session_id,
            new_message=trigger,
        ):
            if not event.content or not event.content.parts:
                continue
            if event.author != COORDINATOR_NAME:
                continue
            for part in event.content.parts:
                text = getattr(part, "text", None)
                if text and text.strip():
                    await q.put({
                        "type": "coordinator_message",
                        "payload": {"role": "coordinator", "text": text.strip()},
                    })
    finally:
        await q.put(None)


# ---------------------------------------------------------------------------
# Turn 1: POST /api/pipeline/run
# ---------------------------------------------------------------------------

class PipelineRunRequest(BaseModel):
    message: str


@app.post("/api/pipeline/run")
async def pipeline_run(body: PipelineRunRequest):
    """Start coordinator Turn 1. Returns an SSE stream of pipeline events."""
    session_id = str(uuid.uuid4())
    q = create_queue(session_id)

    session_service = InMemorySessionService()
    _session_services[session_id] = session_service

    adk_session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=_OPERATOR_USER_ID,
        state={"_sse_session_id": session_id},
    )

    coordinator = build_coordinator()
    runner = Runner(
        agent=coordinator,
        app_name=APP_NAME,
        session_service=session_service,
    )
    store_session(session_id, runner, adk_session)

    asyncio.create_task(
        _run_coordinator_turn(runner, session_id, adk_session.id, body.message, q)
    )

    return StreamingResponse(
        _drain_queue(session_id, q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Turn 2: POST /api/pipeline/decisions
# ---------------------------------------------------------------------------

class PipelineDecisionsRequest(BaseModel):
    session_id: str
    decisions: dict  # {approval_id: {decision, notes?}}


@app.post("/api/pipeline/decisions")
async def pipeline_decisions(body: PipelineDecisionsRequest):
    """Resume coordinator with operator decisions. Returns an SSE stream."""
    entry = get_session(body.session_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="session not found")

    q = create_queue(body.session_id)

    # Format decisions as a structured coordinator message.
    lines = ["Operator submitted decisions:"]
    for apid, dec in body.decisions.items():
        decision_str = dec.get("decision", "approved")
        notes = dec.get("notes", "")
        line = f"  {apid}: {decision_str}"
        if notes:
            line += f" — notes: {notes}"
        lines.append(line)
    message = "\n".join(lines)

    asyncio.create_task(
        _run_coordinator_turn(
            entry.runner, body.session_id, entry.session.id, message, q
        )
    )

    return StreamingResponse(
        _drain_queue(body.session_id, q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
