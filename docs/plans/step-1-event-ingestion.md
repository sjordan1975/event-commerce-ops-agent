# Step 1 — Event Ingestion: Implementation Plan

> **Reframed for D-021** (2026-05-26). Step 1 delivers the `ingest_event_batch` capability — one agent-facing tool that wraps three internal Python functions (`compute_timeliness`, `record_event`, `record_assets`). Agent-facing surface collapses from the pre-reframe 3 atomic `FunctionTool`s to 1 capability per `docs/strategic-agent-reframe.md` § The capability surface. Trace eval premise shifts from sequencing-shaped to outcome-shaped. The three internal wrappers themselves are unchanged. `PreconditionError` foundation class also lands in this step (used cross-capability from Step 2 onward).

## What this capability delivers

Operator provides an image batch (local or GCS paths) + event metadata (teams, score, venue, kick-off time, outcome type). The agent calls `ingest_event_batch` exactly once with structured event metadata extracted from the operator's natural-language prompt. The capability internally:

1. Validates `event_metadata` into an `Event` Pydantic model (`PreconditionError` if fields are missing or invalid)
2. Computes `timeliness` using the fixed formula
3. Writes the event document to `events`
4. Bulk-inserts all images to `assets` with `status="ingested"`

Returns `{"event_id": str, "asset_ids": list[str]}` to agent state. Consumed by whichever capability the agent invokes next (typically `build_event_context`, `find_similar_assets`, or `score_assets_with_vision` — order among the three is the agent's choice per D-021's enforced-vs-emergent split).

Trace eval at `tests/evals/test_step_1_trace.py` satisfies D-020's per-capability requirement (pass rate ≥ 95% across 20 reps is the ship gate).

Prerequisite: Step 0 foundation + Step 0.5 refactor complete. `MongoMCPClient` exists at `src/db/client.py`; `agent.tools` is empty by default; D-019 enforcement test on `main`.

---

## The capability surface (D-019 + D-021)

| Tool | Type | Why |
| --- | --- | --- |
| `ingest_event_batch` | FunctionTool (agent-facing capability) | The one Step 1 agent-facing tool. Internally orchestrates `compute_timeliness`, `record_event`, `record_assets` (none of which are exposed to the agent). |

Per D-021, the agent-facing surface is a small set of mid-granularity capabilities. The internal wrappers (`compute_timeliness`, `record_event`, `record_assets`) remain as Python functions for unit testing and reuse — they are not registered as `FunctionTool`s on the agent. D-019 still applies: raw MongoDB MCP tools are not exposed; `MongoMCPClient` is the programmatic client; domain wrappers in `src/db/` call it internally.

**Directory convention introduced in Step 1:** agent-facing capabilities live in `src/capabilities/`; internal MongoDB plumbing stays in `src/db/`. The separation makes the D-019 + D-021 distinction structural. Sets the pattern for the 8 future capabilities (some of which — `request_human_approval`, `execute_approved_campaigns`, `propose_review_queue` — aren't even mostly-MongoDB).

---

## What the LLM does in this capability

Two reasoning tasks, both bounded:

1. **Natural-language extraction** — assemble the `event_metadata` dict from the operator's input. Example: *"We just finished Argentina vs France 3-2. Photos in /tmp/wc-final/. Match started 19:00 UTC, finished ~20 min ago."* →

   ```python
   event_metadata = {
       "name": "Argentina vs France",
       "home_team": "Argentina",
       "away_team": "France",
       "location": None,                            # not specified by operator; allow null
       "start_date": "<today>T19:00:00Z",           # date inferred from "today" + current time
       "final_score": "Argentina 3-2 France",
       "outcome_type": "upset_victory",             # categorical judgment (France was favored)
   }
   ```

   This is the bulk of the agent's work in Step 1. The `outcome_type` categorization is a real judgment call — for *"Argentina vs France 3-2"* the agent must infer which team was favored and classify accordingly (one of `upset_victory`, `extra_time_win`, `expected_win`, `draw`).

2. **One tool call + scoped termination** — call `ingest_event_batch(images, event_metadata)`, verify the return shape, emit terminal text reporting what was ingested. Do not attempt to call other capabilities (there are none registered yet in Step 1).

The LLM does **not** reason about timeliness math (computed internally), MongoDB schemas (the wrapper handles them), or the order of internal operations (the capability orchestrates `compute_timeliness` → `record_event` → `record_assets` as one atomic operation from the agent's view).

System prompt `prompts/v2/agent_system.md` is active. Per its CoT directive, the agent emits a one-sentence rationale before the tool call. Load-bearing for trace eval diagnosis per `spike/adk_event_capture.py`.

---

## What the capability does internally

```text
ingest_event_batch(images: list[str], event_metadata: dict) → {"event_id": str, "asset_ids": list[str]}
    1. Validate event_metadata into an Event Pydantic model
         (raises PreconditionError with self-correcting message on missing/invalid fields)
    2. compute_timeliness(event.outcome_type, event.start_date) → set event.timeliness
    3. record_event(event) → event_id
    4. Construct Asset models for each image path, status="ingested"
    5. record_assets(event_id, assets) → asset_ids
    6. Return {"event_id": event_id, "asset_ids": asset_ids}
```

The three internal wrappers each carry their own validation and contract. The capability composes them in this fixed order — that order is mechanically required (timeliness must be on the event before insert; event_id is foreign key for assets). The agent sees this as one atomic operation.

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

Computed inside `ingest_event_batch`. Not visible to the agent. Not scored per image by Gemini.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | Pydantic models | `src/models.py` | `Event` and `Asset` document shapes; validated inside the capability and internal wrappers |
| 2 | `PreconditionError` class | `src/errors.py` (new file) | Wrapper-level exception with self-correcting message format per `strategic-agent-reframe.md` § Enforced vs. emergent. First usage: `ingest_event_batch` input validation. Cross-cutting foundation work — all future capabilities reuse it. |
| 3 | Timeliness calculator | `src/timeliness.py` | Pure function; formula above; **internal — not an agent-facing tool** |
| 4 | Lazy client accessor | `src/db/__init__.py` | `get_client()` returns lazy-instantiated `MongoMCPClient` singleton (avoids env reads at import) |
| 5 | `record_event` wrapper | `src/db/events.py` | Validates Event, calls MongoDB insert-many; **internal** |
| 6 | `record_assets` wrapper | `src/db/assets.py` | Validates list of Assets, calls MongoDB insert-many; **internal** |
| 7 | `ingest_event_batch` capability | `src/capabilities/ingest.py` (new file) | The one agent-facing tool. Orchestrates the three internal operations. |
| 8 | FunctionTool registration | `src/capabilities/__init__.py` (new file) | Exports `all_function_tools = [FunctionTool(ingest_event_batch)]` — the production tool list. Only one tool in Step 1; grows as later steps add capabilities. |
| 9 | Auto-wire in agent shell | `src/agent.py` | `build_agent()` imports `all_function_tools` from `src.capabilities` and prepends to `extra_tools`. Production callers do `build_agent()`; tests pass `extra_tools=[...]` to extend. |
| 10 | Tests | `tests/test_models.py`, `tests/test_errors.py`, `tests/test_timeliness.py`, `tests/test_step_1.py`, `tests/evals/test_step_1_trace.py` | TDD for unit logic (models, errors, timeliness, wrappers, capability) + trace eval for agent-facing behavior |

Reused from Step 0.5: `src/db/client.py` (`MongoMCPClient`). Not recreated.

The D-019 enforcement test on `main` continues to pass after auto-wire — adding `FunctionTool(ingest_event_batch)` does not violate the no-raw-MCP rule (the capability wraps domain operations, not raw MCP).

---

## Dependency order

1. **Pydantic models** (`src/models.py`) — `Event`, `Asset`; validates at the capability and wrapper boundaries
2. **Update conftest helpers** (`tests/conftest.py`) — `build_valid_event` and `build_valid_asset` return Pydantic instances
3. **`PreconditionError` class** (`src/errors.py`) — small (~15 lines); shape: `PreconditionError(capability: str, missing: list[str], remediation: str)` with `__str__` rendering as *"Cannot do X for Y: missing Z (call Z-producer first)"*. Cross-cutting foundation work — lands now so subsequent capabilities reuse it from day one.
4. **Timeliness calculator** (`src/timeliness.py`) — pure function, no internal imports
5. **Lazy client accessor** (`src/db/__init__.py`) — `get_client()` returning a module-level lazy singleton
6. **`record_event` wrapper** (`src/db/events.py`) — calls `get_client().call("insert-many", ...)`; testable by monkeypatching `src.db.get_client`
7. **`record_assets` wrapper** (`src/db/assets.py`) — same pattern
8. **`ingest_event_batch` capability** (`src/capabilities/ingest.py`) — composes timeliness + record_event + record_assets; validates input via `PreconditionError`; returns `{event_id, asset_ids}`
9. **FunctionTool list** (`src/capabilities/__init__.py`) — define `all_function_tools = [FunctionTool(ingest_event_batch)]`
10. **Auto-wire** (`src/agent.py`) — `from src.capabilities import all_function_tools`; `build_agent()` prepends to `extra_tools`
11. **Trace eval scaffolding** (`tests/evals/conftest.py`) — helpers reused across all capability evals: mocked-client injection, trace classifier (text / tool_call / tool_response per `spike/adk_event_capture.py`), failure-trace dumper
12. **Trace eval — single-run** (`tests/evals/test_step_1_trace.py`) — outcome-shaped assertions per the verification table below
13. **Trace eval — pass rate** — N=20 repetition harness; ≥ 95% threshold per D-020

---

## Tool docstring (matters for the agent's planning)

The docstring is what the LLM reads to decide what to call. It is part of the implementation, not commentary on it.

```python
def ingest_event_batch(images: list[str], event_metadata: dict) -> dict:
    """Ingests an event and its associated images.

    Records the event with computed timeliness and bulk-inserts all images
    with status='ingested'. Returns {"event_id": str, "asset_ids": list[str]}.

    Required fields in event_metadata:
        - name, home_team, away_team, final_score (strings)
        - start_date (ISO 8601 UTC string, e.g. "2026-07-14T19:00:00Z")
        - outcome_type (one of: upset_victory, extra_time_win, expected_win, draw)
    Optional:
        - location (string)

    Raises PreconditionError if required fields are missing or outcome_type is invalid;
    the error message identifies the missing/invalid field for self-correction.

    Typically the first capability called for a new event batch — call before
    build_event_context, find_similar_assets, or score_assets_with_vision.
    """
```

The docstring is the agent's contract — what to pass, what to expect back, what failure looks like, when it typically fires.

---

## System prompt context

`prompts/v2/agent_system.md` is active (per Phase A item 6 of the D-021 reframe propagation). It carries:

1. **Role + strategist framing** — operations agent in commerce business; queue assembly is the judgment surface
2. **End-to-end job scope** — 5 phases from ingest through outcome recording
3. **Schema overview** — conceptual; the agent does not need field-level detail
4. **How you work** — `PreconditionError` handling, order among independent operations, HITL semantics, termination clause
5. **CoT directive** — *"Before each tool call, briefly state in one sentence why you are calling it and what you expect to learn or accomplish."*

In Step 1 specifically, the agent has only `ingest_event_batch` registered. The v2 prompt's broader pipeline language (queue assembly, drafting, execution) is forward-compatible but not currently actionable — the agent should call ingest, confirm success, and emit terminal text. **The Step 1 eval's operator prompt should scope the work** (*"Ingest this event batch."*) — not *"Take this batch all the way to published campaigns,"* which would set the agent up to try non-existent tools. Operator-scoped tasks are a real production pattern too (an operator might want to ingest a batch and review the queue later in a separate session).

---

## Risks

| Risk | Mitigation |
| --- | --- |
| Agent extracts wrong `outcome_type` from natural language (e.g., calls a 1-1 draw an `upset_victory`) | Pydantic validates the enum; capability raises `PreconditionError` with self-correcting message. Trace eval asserts on `outcome_type` correctness against the operator's narrative. Hardest extraction judgment in Step 1. |
| Agent fails to extract `start_date` (no explicit date in operator's natural-language input) | The agent infers "today" from current time. Trace eval asserts on ISO 8601 format and the date matches the run's date. |
| Agent calls `ingest_event_batch` once per image instead of with the full batch | Docstring's `list[str]` signature + "Bulk-inserts" wording should prevent. Trace eval asserts capability call count = 1. |
| Agent tries to call other capabilities after ingestion (queue assembly, drafting) — those tools don't exist yet in Step 1 | Operator prompt scopes the work explicitly (*"Ingest this event batch."*). Eval tolerates the agent recognizing scope and emitting terminal text without further calls. If the agent insists on calling non-existent tools, that's a system-prompt issue worth investigating per the eval's remediation playbook. |
| `PreconditionError` message format inconsistency surfaces in later capabilities | Ship the class with a clear shape (`capability`, `missing`, `remediation`) and a `__str__` method that renders consistently. Step 1 sets the pattern; later capabilities inherit it without re-debating format. |
| `McpToolset` spawns `npx mongodb-mcp-server` subprocess — can't call live MongoDB in unit tests | Tests inject a mocked `MongoMCPClient` via monkeypatching `src.db.get_client`. Trace evals run without hitting Atlas. Live-DB integration evals run on merge to main only. |
| GCS vs local paths in MVP | `content_url` is a plain string in the `Asset` model; no GCS URI validation in MVP. |

**Retired risk** *(pre-D-021)*: "agent ignores `compute_timeliness` output and hallucinates timeliness value." Moot — `compute_timeliness` is internal; the agent never sees the value. D-019 Open Q #6's hybrid-wrapper fallback is no longer needed for this chain.

---

## Env vars required

Same as Step 0 — no new vars.

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v` | `Event` validates required fields including `timeliness`; rejects unknown `outcome_type`. `Asset` validates `event_id` linkage and default `status="ingested"`. |
| Errors | `.venv/bin/python -m pytest tests/test_errors.py -v` | `PreconditionError` constructs with `(capability, missing, remediation)`; `__str__` renders the self-correcting message in the expected format. |
| Timeliness | `.venv/bin/python -m pytest tests/test_timeliness.py -v` | 0h → base score; 4h → base/2; 8h → base/4. |
| Wrappers + capability | `.venv/bin/python -m pytest tests/test_step_1.py -v` | `record_event` and `record_assets` validate and call mocked client with correct collection + document/list; `ingest_event_batch` orchestrates all three in the right order, raises `PreconditionError` on missing fields, returns the expected dict shape. |
| Agent integration | `.venv/bin/python -m pytest tests/ -v` | Full unit suite green. |
| **Trace eval — outcome-shaped (single run)** | `.venv/bin/python -m pytest tests/evals/test_step_1_trace.py -v` | Given a realistic ingestion prompt (e.g. *"We just finished Argentina vs France 3-2. Photos are in /tmp/wc-final/. Match started 19:00 UTC, finished ~20 min ago. Ingest this batch."*): (a) agent calls `ingest_event_batch` exactly once; (b) `event_metadata` has correctly-extracted fields (`home_team="Argentina"`, `away_team="France"`, `outcome_type="upset_victory"`, `start_date` is ISO 8601 UTC for today at 19:00); (c) mocked client recorded one `insert-many` on `events` and one on `assets` with all images; (d) the `events` document has `timeliness` set (computed internally — non-null); (e) reasoning text is present before the tool call (CoT directive working); (f) agent emits terminal text after success; (g) on assertion failure, the full trace (tool calls + reasoning text + LLM responses) is dumped via `dump_trace()`. |
| **Trace eval — pass rate** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_1_trace.py -v` | ≥ 19/20 runs pass all seven assertions (95% threshold per D-020). |

The trace evals are automated, not manual. They are the regression net for the capability's agent-facing behavior. Per `docs/evaluation-strategy.md`, Step 1's surface exercises **failure categories 1, 3, 5** (tool selection, tool arguments — the natural-language extraction quality, end-state). Strategy coherence (category 6) does not apply to `ingest_event_batch`; it lands when `propose_review_queue` ships in a later step.

---

## Output consumed by

- **The agent's next capability invocation.** The typical next call is `build_event_context(event_id)`, but per D-021's enforced-vs-emergent split, the agent may also choose `find_similar_assets(event_id)` or `score_assets_with_vision(event_id)` first. All three only require ingestion as a prerequisite; order among them is the agent's choice.
- **All subsequent capabilities** — work from `asset_id`s and `event_id` written here. The `assets` document is the central state document touched by nearly every subsequent capability (per `docs/specs/02-architecture.md` § MongoDB Collections).

---

## What changed from the pre-D-021 plan

For anyone reading the git history:

- **Agent-facing surface**: 3 atomic `FunctionTool`s (`compute_timeliness`, `record_event`, `record_assets`) → 1 capability (`ingest_event_batch`). The three wrappers survive as internal Python functions, not registered as tools.
- **Directory layout**: new `src/capabilities/` for agent-facing tools; `src/db/` stays for internal wrappers.
- **New foundation**: `PreconditionError` class lands now (was a separate item 9 in the pre-reframe propagation plan).
- **Trace eval premise**: sequencing-shaped (asserting `compute_timeliness < record_event` etc.) → outcome-shaped (asserting MongoDB state after capability returned + correct natural-language extraction).
- **Retired risk**: the hallucinated-timeliness concern (D-019 Open Q #6) goes away because `compute_timeliness` is no longer agent-visible.
- **Active prompt**: `prompts/v2/agent_system.md` (strategist framing) replaces v1's "plan and execute" framing.
- **Task list T-numbering** in `docs/tasks/step-1-tasks.md` is rewritten correspondingly (Phase B follow-up).
