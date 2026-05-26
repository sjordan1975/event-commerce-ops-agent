# Step 1 — Event Ingestion: Implementation Plan

## What this step delivers

Operator provides an image batch (local or GCS paths) + event metadata (teams, score, venue, kick-off time, outcome type). The agent:

1. Calls `compute_timeliness` (FunctionTool) to compute the timeliness score
2. Calls `record_event` (domain wrapper) to write the event document
3. Calls `record_assets` (domain wrapper) to bulk-insert all images at `status: "ingested"`

Output visible in agent state: `event_id` + list of `asset_id`s. Consumed by Step 2.

Trace evals at `tests/evals/test_step_1_trace.py` satisfy D-020's per-step requirement (failure-rate ≥ 95% across 20 reps is the ship gate).

Prerequisite: Step 0 foundation + Step 0.5 refactor complete. `MongoMCPClient` exists at `src/db/client.py`; `agent.tools` is empty by default; D-019 enforcement test on `main`.

---

## Tool surface (D-019)

| Tool | Type | Why |
|---|---|---|
| `compute_timeliness` | FunctionTool (pure math) | Domain logic central to the project's positioning; agent chains its output into `record_event`. See D-019 Q#6 resolution. |
| `record_event` | FunctionTool (domain wrapper) | Wraps `events insert-many`. Validates the `Event` Pydantic model and writes. |
| `record_assets` | FunctionTool (domain wrapper) | Wraps `assets insert-many`. Validates a list of `Asset` Pydantic models and bulk-writes. |

D-019 supersedes D-018: raw MongoDB MCP tools are not exposed to the agent. `MongoMCPClient` (introduced in Step 0.5) is the programmatic MCP client; domain wrappers in `src/db/` call it internally. The agent's tool surface is the three named operations above.

There is no `ingest_event` mega-wrapper. `record_event` and `record_assets` are split per the splitting principle (db-wrapper-inventory.md): they have different cardinality, different shapes, and could be independently called (backfilling assets for an existing event is a coherent future operation).

---

## What the LLM does in this step

Three small reasoning tasks:

1. **Planning** — figure out from the operator prompt that it needs to compute timeliness, then record the event, then record the assets. Tool docstrings guide this; the system prompt does not hardcode the sequence.
2. **Document construction** — assemble the `Event` and `Asset` field values from the operator's natural-language input (e.g. "Argentina vs France, finished about 20 minutes ago" → `name="Argentina vs France"`, `kickoff_utc` resolved against current time).
3. **Output-to-input chaining** — pass the value returned by `compute_timeliness` into the `event` argument of `record_event`. This chain is the primary thing the trace eval asserts on.

The LLM does **not** reason about timeliness itself (it's a fixed formula) or about MongoDB collection structure (the wrapper handles it).

Per CLAUDE.md's eval discipline and `prompts/v1/agent_system.md`: the agent emits a one-sentence rationale before each tool call. Confirmed load-bearing by `spike/adk_event_capture.py`.

---

## What each wrapper does internally

```text
compute_timeliness(outcome_type, kickoff_utc) → {"timeliness": float, "outcome_type": str}
    Pure Python. No I/O.

record_event(event: Event) → str (event_id)
    Pydantic-validates `event`.
    Calls MongoDB MCP: insert-many on event_commerce.events with [event.model_dump()].
    Returns event.event_id.

record_assets(event_id: str, assets: list[Asset]) → list[str] (asset_ids)
    Pydantic-validates each asset, sets status="ingested" if not already set.
    Calls MongoDB MCP: insert-many on event_commerce.assets with [a.model_dump() for a in assets].
    Returns [a.asset_id for a in assets] in input order.
```

The internal MCP call is the same `insert-many` in both cases. The wrapper boundary is what gives us validation, field-name discipline, and the agent-facing contract.

---

## Timeliness formula

```text
timeliness = base_score × 0.5^(hours_since_kickoff / 4)

base_score by outcome_type:
  upset_victory:   0.95
  extra_time_win:  0.85
  expected_win:    0.60
  draw:            0.40
```

Computed once at ingestion. Not scored per image by Gemini.

---

## Components

| # | Component | File | Purpose |
|---|---|---|---|
| 1 | Pydantic models | `src/models.py` | `Event` and `Asset` document shapes; validated inside the wrappers |
| 2 | Timeliness calculator | `src/timeliness.py` | Pure function; formula above |
| 3 | Lazy client accessor | `src/db/__init__.py` | `get_client()` returns lazy-instantiated `MongoMCPClient` singleton (avoids env reads at import) |
| 4 | Events wrappers | `src/db/events.py` | `record_event` (Step 2 will add `get_event`, etc.) |
| 5 | Assets wrappers | `src/db/assets.py` | `record_assets` (later steps will add more) |
| 6 | FunctionTool registration | `src/db/__init__.py` | Exports `all_function_tools` — the production tool list. Includes `compute_timeliness`, `record_event`, `record_assets` as `FunctionTool`s |
| 7 | Auto-wire in agent shell | `src/agent.py` | `build_agent()` imports `all_function_tools` from `src.db` and prepends to `extra_tools`. Production callers do `build_agent()`; tests pass `extra_tools=[...]` to extend |
| 8 | Tests | `tests/test_models.py`, `tests/test_timeliness.py`, `tests/test_step_1.py`, `tests/evals/test_step_1_trace.py` | TDD for unit logic + trace eval for agentic chain |

Reused from Step 0.5: `src/db/client.py` (`MongoMCPClient` class). Not recreated.

The D-019 enforcement test on `main` continues to pass after auto-wire: it asserts no `McpToolset` in `agent.tools`. Adding `FunctionTool` instances does not violate that — they're domain wrappers, not raw MCP.

---

## Dependency order

1. **Pydantic models** (`src/models.py`) — `Event`, `Asset`; validates at the wrapper boundary
2. **Update conftest helpers** (`tests/conftest.py`) — `build_valid_event` and `build_valid_asset` return Pydantic instances now that models exist (carried over from Step 0.5 audit)
3. **Timeliness calculator** (`src/timeliness.py`) — pure function, no internal imports
4. **Lazy client accessor** (`src/db/__init__.py`) — add `get_client()` returning a module-level lazy singleton (`_client: MongoMCPClient | None = None`; instantiate on first call). Avoids `MONGODB_URI` reads at import time so unit tests stay isolated.
5. **`record_event` wrapper** (`src/db/events.py`) — calls `get_client().call("insert-many", ...)`; testable by monkeypatching `src.db.get_client` to return a `MagicMock`
6. **`record_assets` wrapper** (`src/db/assets.py`) — same pattern
7. **FunctionTool list** (`src/db/__init__.py`) — define `all_function_tools = [FunctionTool(compute_timeliness), FunctionTool(record_event), FunctionTool(record_assets)]`
8. **Auto-wire** (`src/agent.py`) — `from src.db import all_function_tools`; `build_agent()` prepends to `extra_tools` so production callers get the production tool list by default
9. **Trace eval scaffolding** (`tests/evals/conftest.py`) — helpers reused across all step evals: mocked-client injection, trace classifier (text / tool_call / tool_response per `spike/adk_event_capture.py`), failure-trace dumper
10. **Trace eval — single-run** (`tests/evals/test_step_1_trace.py`) — six assertions per the verification table below
11. **Trace eval — pass-rate** — N=20 repetition harness; ≥ 95% threshold per D-020

---

## Tool docstrings (matters for planning)

The docstrings are what the LLM reads to decide which tool to call. They are part of the implementation, not commentary on it.

```python
def compute_timeliness(outcome_type: str, kickoff_utc: str) -> dict:
    """Computes the timeliness score for an event from its outcome type and kickoff time.

    The `timeliness` field is required on every events document; this is the only
    way to produce it. Call this before record_event.

    Returns {"timeliness": <float>, "outcome_type": <str>}.
    """

def record_event(event: Event) -> str:
    """Records an event in the events collection. Returns the event_id.

    The event must include a `timeliness` value — call compute_timeliness first
    and pass the returned float into event.timeliness.
    """

def record_assets(event_id: str, assets: list[Asset]) -> list[str]:
    """Bulk-records image assets for an event. Returns asset_ids in input order.

    Call this after record_event; pass the returned event_id from that call.
    Each asset is stored with status="ingested" by default.
    """
```

The "call this before / after X" phrasing is what guides the LLM's planning without hardcoding the sequence in the system prompt.

---

## System prompt context required

`prompts/v1/agent_system.md` must include:

1. **Schema overview block** — conceptual, not field-level. See db-wrapper-inventory.md for the full block. The agent does not need field names; the wrappers carry that contract.
2. **CoT directive** — `"Before each tool call, briefly state in one sentence why you are calling it and what you expect to learn or accomplish."` Required content per `spike/adk_event_capture.py` findings; load-bearing for trace eval diagnosis.

No field-level event/asset schema in the prompt. That detail lives in the Pydantic models, enforced at the wrapper boundary.

---

## Risks

| Risk | Mitigation |
|---|---|
| Agent skips `compute_timeliness` and calls `record_event` directly | `Event` Pydantic model marks `timeliness` required → wrapper raises → agent retries. Trace eval asserts the sequencing. |
| Agent calls `compute_timeliness`, ignores the result, passes a hallucinated value to `record_event` | Trace eval asserts `compute_timeliness.output.timeliness == record_event.args.event.timeliness`. Fallback per D-019 Q#6: hybrid `record_event` that defends if pass rate < 90%. |
| Agent calls `record_assets` separately per image instead of once with a batch | Trace eval asserts `record_assets` called exactly once with the full list. Docstring "Bulk-records" + the explicit `list[Asset]` signature should prevent this; eval is the safety net. |
| McpToolset spawns `npx mongodb-mcp-server` subprocess — can't call live MongoDB in unit tests | Tests inject a mocked client (the seam introduced in dependency step 3). Trace evals run without hitting Atlas. Live-DB integration evals run on merge to main only. |
| GCS vs local paths in MVP | `content_url` is a plain string in the `Asset` model; no GCS URI validation in MVP. |

---

## Env vars required

Same as Step 0 — no new vars.

---

## Verification checkpoints

| After | Command | Must pass |
|---|---|---|
| Models | `.venv/bin/python -m pytest tests/test_models.py -v` | `Event` validates required fields including `timeliness`; rejects unknown `outcome_type`. `Asset` validates `event_id` linkage and default `status="ingested"`. |
| Timeliness | `.venv/bin/python -m pytest tests/test_timeliness.py -v` | 0h → base score; 4h → base/2; 8h → base/4 |
| Wrappers | `.venv/bin/python -m pytest tests/test_step_1.py -v` | `record_event` validates and calls mocked client with correct collection + document; `record_assets` validates the list and calls mocked client with bulk insert |
| Agent integration | `.venv/bin/python -m pytest tests/ -v` | Full unit suite green |
| **Trace eval — tool sequencing** | `.venv/bin/python -m pytest tests/evals/test_step_1_trace.py -v` | Given a realistic ingestion prompt (e.g. "We just finished Argentina vs France 3–2. Photos are in /tmp/wc-final/. Match started 19:00 UTC, finished ~20 min ago. Get them into the system."): (a) agent calls `compute_timeliness` **before** `record_event`; (b) the `timeliness` value passed to `record_event` **equals the value returned by `compute_timeliness`** (no hallucination); (c) `record_event` is called exactly once; (d) `record_assets` is called exactly once with all images and `status="ingested"`; (e) intermediate reasoning text is present for each tool call (CoT directive working); (f) on assertion failure, the test dumps the full trace (tool calls + reasoning text) for diagnosis. |
| **Trace eval — pass rate** | `SPIKE_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_1_trace.py -v` | ≥ 19/20 runs pass all six assertions (95% threshold per D-020). |

The trace evals are automated, not manual. They are the regression net for the agentic chain. See `docs/plans/evaluation-strategy.md` for the eval framework and failure-diagnosis approach these tests instantiate.

---

## Output consumed by

- **Step 2:** `get_event(event_id)` (Step 2 will add this wrapper to `events.py`); `get_assets_for_event(event_id)` (Step 2 will add to `assets.py`)
- **All subsequent steps:** work from `asset_id`s written here; `assets` document is the central state document updated at every step
