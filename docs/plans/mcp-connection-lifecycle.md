# MCP Connection Lifecycle

**Status:** design (Phase B — implement when `src/api/` is built). Minimal `client.py` hardening already landed (D-035). Decision: D-035.

## The trap: treating MCP like REST

The MongoDB MCP server is the mandated, load-bearing data layer (partner track, D-001/D-019). The instinct is to treat each tool call like a REST request — open, do work, close:

```
for request in requests:
    session = connect()      # spawn npx mongodb-mcp-server, MCP handshake, discover tools
    call_tool()
    disconnect()
```

That pays the most expensive part of the lifecycle — process spawn + `create_session` + tool discovery — on **every** transaction. It also makes the npx cold start (and any registry/network stall) a per-request hazard. Empirically, a fresh connect+call cycle ran ~2.9s to ready; reused, the same call is <1s. The cost belongs at boot, once.

The correct mental model is a **database connection pool / WebSocket**, not REST:

```
backend starts → connect once → reuse the live session for thousands of operations
```

## Current state (`src/db/client.py`)

`MongoMCPClient` is a module-level singleton (`get_client()`); `McpToolset` is created once and `_ensure_tools()` caches tool discovery. So the session **is** reused across the process. What's missing is the lifecycle *around* that singleton:

| Recommendation | Status |
|---|---|
| Singleton/shared session, reuse | ✅ `get_client()` singleton |
| Cache tool discovery | ✅ `_ensure_tools()` |
| Pinned, network-safe server launch | ✅ D-035: pinned version + `--prefer-offline` |
| Eager connect at startup (not lazy-on-first-request) | ⚠️ `warm()` hook exists (D-035); caller must invoke it at boot |
| Fail fast when MCP unavailable | ⚠️ `warm(timeout=)` bounds the async init; full gating is Phase B |
| Background reconnect on dropped session | ❌ Phase B |
| Health surface (separate from request handling) | ❌ Phase B |

The lazy-init gap matters: as-is, the **first** user request pays the cold start and can stall on it. `warm()` lets the entrypoint move that cost to boot; the full manager makes unavailability a fast, explicit failure.

## Target design (the `src/api` MCP connection manager)

Built into the FastAPI backend (D-033), since that is the long-lived process fronting the demo.

1. **Connect at startup.** FastAPI `lifespan` handler calls `get_client().warm()` → establish session, discover tools, cache. Mark MCP `READY`.
2. **Keep the session alive.** One shared session for the process lifetime; every request uses it. Never connect per-request.
3. **Fail fast when unavailable.** If `warm()` fails (or the session is down), requests return `503 {"error": "data service unavailable"}` immediately instead of hanging. Readiness is checked, not discovered the hard way.
4. **Background reconnect.** On a dropped session, serve degraded responses and run a background reconnect loop; user requests are never responsible for re-establishing the connection.
5. **Cache tool discovery.** Already done — discover once at warm, invoke directly thereafter. Do not re-discover per connection.
6. **Health monitor, exposed separately from request handling.** A `/health` (or `/health/mcp`) endpoint reporting: session connected/disconnected, last successful tool call, reconnect attempts, tool-discovery status. This is the single highest-leverage debugging aid — it tells you instantly whether a demo failure is application logic or MCP lifecycle.

```
REST layer
    ↓
service layer
    ↓
MCP manager (singleton)  ──→  health surface
    ↓
MCP session (persistent)
    ↓
mongodb-mcp-server (npx, pinned)  ──→  Atlas
```

## Health surface in the UI (operator console)

Point 6 isn't only a debugging aid — surfaced in the operator console it becomes the **demo's proof that MongoDB MCP is load-bearing**, not invisible plumbing. A small status widget pinned to the **bottom of the sidebar** shows the live MCP session state: the visible payoff of all the connection-lifecycle work.

**Signals shown** (the four from point 6, plus version):
- session **connected / reconnecting / unavailable**
- **last successful tool call** (relative time, e.g. "2s ago")
- **reconnect attempts**
- **tool-discovery status** (e.g. "43 tools")
- pinned server version (`1.11.0`)

**States, honestly degraded:** green dot = connected; amber = reconnecting; red = unavailable. The widget must reflect **true** state — red when the session is actually down — or it is theatre that quietly undoes the "health separate from request handling" principle. A permanently-green indicator is worse than none.

**Compact, expandable:** collapsed = colored dot + "MongoDB MCP" + state; expand (hover/click) for the detail above. Poll `/health` every few seconds — a status light needs no SSE.

**Two-layer, matching the Phase A/B split:**
- **Phase A (the `ui/phase-a` branch — pure mock):** build the widget against a mock health payload. This lands the layout and **serves as the visual contract for Phase B** — the widget's shape *is* the spec for the `/health` payload it will eventually consume.
- **Phase B:** make the backend match. Today `/health` returns only `{mcp_ready, mcp_error}`, and `MongoMCPClient` tracks only `_ready` + tool discovery — the manager (points 4/6) must additionally track **last-successful-call timestamp, reconnect attempts, and last-error detail**, and `/health` must return them. The widget then polls the real endpoint — a single swap, no UI change.

## Launch hardening (why pinned + `--prefer-offline`, and Cloud Run)

`npx -y mongodb-mcp-server@latest` resolves "latest" from the npm registry on every cold start; a bare range (`@1`) likewise resolves the newest matching version. In network-restricted environments that resolve blocks the event loop and hangs *before the server starts* — observed repeatedly in the sandbox; the harness's own server avoids it by running a pinned, cached version. Mitigations, in order of robustness:

- **Pin the version** (`MONGODB_MCP_VERSION`, default `1.11.0`) — deterministic, no "newest" lookup.
- **`--prefer-offline`** — use the local npm cache; touch the registry only if the version is genuinely absent. (Now in `client.py`.)
- **Pre-install for Cloud Run** — bake the pinned `mongodb-mcp-server` into the image and invoke the installed binary directly, so there is no runtime npx/registry step at all. This is the production target; it also makes `warm()` fast and reliable.

## Known limitation of the minimal hardening

`warm(timeout=)` bounds the *async* portion of init. A subprocess spawn that blocks the event loop synchronously (e.g. npx truly wedged) is not interruptible by `asyncio.wait_for`; `--prefer-offline` removes the main cause, and the Phase-B manager closes the rest by spawning/​supervising the server out-of-band with a hard kill + reconnect. Until then, the demo-safe posture is: pinned + offline launch, `warm()` at boot, and a readiness check before serving.
