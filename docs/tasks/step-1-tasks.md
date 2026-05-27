# Step 1 — Event Ingestion: Task List

> **Reframed for D-021** (2026-05-26). Tasks T-1.1–T-1.3 survive intact (Pydantic models + conftest helpers). T-1.4 is **new** (`PreconditionError` foundation). T-1.5 and T-1.6 are timeliness + lazy client (renumbered). T-1.7 and T-1.8 still build the `record_event` + `record_assets` wrappers but as **internal Python functions only — not registered as agent-facing `FunctionTool`s**. T-1.9 is **new** (the `ingest_event_batch` capability). T-1.10 + T-1.11 register the single capability as the agent's tool surface. T-1.12 + T-1.13 + T-1.14 + T-1.15 are the eval and final-verify tasks (trace eval is rewritten from sequencing-shaped to outcome-shaped per D-021). Full plan: `docs/plans/step-1-event-ingestion.md`.

Prerequisite: Step 0 foundation + Step 0.5 refactor merged to `main`. `MongoMCPClient` exists at `src/db/client.py`. `build_agent()` is a pass-through shell. 5/5 foundation tests passing.

Design decisions baked in (see `docs/plans/step-1-event-ingestion.md` for rationale):
- Lazy MongoDB MCP singleton via `get_client()` in `src/db/__init__.py`.
- One agent-facing `FunctionTool`: `ingest_event_batch`, registered in `src/capabilities/__init__.py` as `all_function_tools`.
- Three internal Python functions (`compute_timeliness`, `record_event`, `record_assets`) — not exposed to the agent.
- `PreconditionError` class lands here as cross-capability foundation work.
- `build_agent()` auto-wires `all_function_tools` from `src.capabilities`.

---

## T-1.1: Create `Event` Pydantic model

Files: `src/models.py`, `tests/test_models.py`
Acceptance: `Event` validates required fields (`event_id`, `name`, `home_team`, `away_team`, `location`, `start_date`, `final_score`, `outcome_type`, `timeliness`, `ingested_at`); rejects unknown `outcome_type` (must be one of: `upset_victory`, `extra_time_win`, `expected_win`, `draw`); `timeliness` must be a float in `[0.0, 1.0]`. `location` is nullable per D-021's reframe note (operator may omit).
Verify: `.venv/bin/python -m pytest tests/test_models.py::test_event -v`

---

## T-1.2: Create `Asset` Pydantic model

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance: `Asset` validates required fields (`asset_id`, `event_id`, `content_url`, `status`, `upload_date`); nullable fields (`product_route`, `queue_type`, `embedding`, `scores`, `campaign_id`) default to `None`; `status` defaults to `"ingested"`.
Verify: `.venv/bin/python -m pytest tests/test_models.py::test_asset -v`

---

## T-1.3: Update conftest helpers to return Pydantic models

Files: `tests/conftest.py`
Acceptance: `build_valid_event(**overrides)` returns an `Event` instance; `build_valid_asset(**overrides)` returns an `Asset` instance. Default field values match the JSON examples in `docs/specs/02-architecture.md` § MongoDB Collections. Carried over from `docs/plans/step-0.5-refactor.md` § 2.
Verify: `.venv/bin/python -c "from tests.conftest import build_valid_event, build_valid_asset; from src.models import Event, Asset; assert isinstance(build_valid_event(), Event); assert isinstance(build_valid_asset(), Asset); print('ok')"`

---

## T-1.4: Create `PreconditionError` foundation class (NEW per D-021)

Files: `src/errors.py`, `tests/test_errors.py`
Acceptance: `PreconditionError(capability: str, context: str, missing: dict[str, str])` constructs with all three fields stored as attributes. `__str__` renders a multi-line, self-correcting message in the format:

```
Cannot do <capability> for <context>:
  - <missing_key_1> (<remediation_1>)
  - <missing_key_2> (<remediation_2>)
```

Subclasses `Exception`. Cross-cutting — used by every capability wrapper that has data dependencies (per `docs/plans/strategic-agent-reframe.md` § Enforced vs. emergent). First usage in Step 1 is `ingest_event_batch` input validation for missing/invalid `event_metadata` fields.

Tests: (a) constructs with valid args; (b) `__str__` matches the expected format including all missing entries; (c) raisable and catchable as a normal Python exception; (d) `capability`, `context`, `missing` accessible as attributes after raise/catch.
Verify: `.venv/bin/python -m pytest tests/test_errors.py -v`

---

## T-1.5: Create timeliness calculator

Files: `src/timeliness.py`, `tests/test_timeliness.py`
Acceptance: `compute_timeliness(outcome_type: str, kickoff_utc: str) -> dict` returns `{"timeliness": <float>, "outcome_type": <str>}` per the formula `base_score × 0.5^(hours_since_kickoff / 4)`. Base scores: `upset_victory=0.95`, `extra_time_win=0.85`, `expected_win=0.60`, `draw=0.40`. 0h → base score; 4h → base/2; 8h → base/4. Raises `ValueError` for unknown `outcome_type`. Accepts ISO 8601 string for `kickoff_utc` (with `Z` suffix or `+00:00`). **Internal function — not registered as an agent-facing `FunctionTool` per D-021.**
Verify: `.venv/bin/python -m pytest tests/test_timeliness.py -v`

---

## T-1.6: Add lazy `get_client()` accessor

Files: `src/db/__init__.py`
Acceptance: `get_client()` returns a module-level lazy singleton `MongoMCPClient` (`_client: MongoMCPClient | None = None`; instantiated on first call). Repeat calls return the same instance. Does not read `MONGODB_URI` at module import time.
Verify: `.venv/bin/python -c "from src.db import get_client; c1 = get_client(); c2 = get_client(); assert c1 is c2; print('ok')"` (requires `MONGODB_URI` in `.env`)

---

## T-1.7: Implement `record_event` internal wrapper

Files: `src/db/events.py`, `tests/test_step_1.py`
Acceptance: `record_event(event: Event) -> str` is async; validates the Pydantic `Event`; calls `get_client().call("insert-many", {"database": "event_commerce", "collection": "events", "documents": [event.model_dump(mode="json")]})`; returns `event.event_id`. **Internal Python function — not wrapped in `FunctionTool`, not registered with the agent per D-021.** Docstring: *"Internal: records an event in the events collection. Called by the `ingest_event_batch` capability; not agent-facing. Returns the event_id."*
Unit test monkeypatches `src.db.get_client` to return a `MagicMock`; asserts the wrapper passes correct collection name and documents list.
Verify: `.venv/bin/python -m pytest tests/test_step_1.py::test_record_event -v`

---

## T-1.8: Implement `record_assets` internal wrapper

Files: `src/db/assets.py`, `tests/test_step_1.py` (extend)
Acceptance: `record_assets(event_id: str, assets: list[Asset]) -> list[str]` is async; Pydantic-validates each asset; sets `status="ingested"` if not already set; calls `get_client().call("insert-many", {"database": "event_commerce", "collection": "assets", "documents": [a.model_dump(mode="json") for a in assets]})`; returns `[a.asset_id for a in assets]` in input order. **Internal Python function — not wrapped in `FunctionTool`, not registered with the agent per D-021.** Docstring: *"Internal: bulk-records image assets for an event. Called by the `ingest_event_batch` capability; not agent-facing. Returns asset_ids in input order."*
Unit test monkeypatches `src.db.get_client`; asserts batch shape and order preservation.
Verify: `.venv/bin/python -m pytest tests/test_step_1.py::test_record_assets -v`

---

## T-1.9: Implement `ingest_event_batch` capability (NEW per D-021)

Files: `src/capabilities/__init__.py` (new file — empty for now, populated by T-1.10), `src/capabilities/ingest.py`, `tests/test_step_1.py` (extend)
Acceptance: `ingest_event_batch(images: list[str], event_metadata: dict) -> dict` is async; this is **the one agent-facing capability for Step 1**.

Behavior:
1. Validate `event_metadata` contains required fields (`name`, `home_team`, `away_team`, `final_score`, `start_date`, `outcome_type`). Raise `PreconditionError(capability="ingest_event_batch", context="event_metadata", missing={...})` if any are missing or `outcome_type` is invalid — with self-correcting remediation messages.
2. Generate a fresh `event_id` (uuid).
3. Call `compute_timeliness(event_metadata["outcome_type"], event_metadata["start_date"])` → get the `timeliness` float.
4. Construct an `Event` Pydantic instance with the validated metadata + computed `timeliness` + `event_id` + `ingested_at=now()`.
5. Call `record_event(event)` → confirm `event_id`.
6. Construct an `Asset` Pydantic instance per image (status="ingested", `event_id` linked).
7. Call `record_assets(event_id, assets)` → get `asset_ids` in order.
8. Return `{"event_id": event_id, "asset_ids": asset_ids}`.

Docstring (load-bearing for the agent):
```python
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

Unit test monkeypatches `src.db.get_client`; asserts the capability orchestrates `compute_timeliness` → `record_event` → `record_assets` in the right order; asserts `PreconditionError` raised with correct shape on missing fields; asserts return shape `{"event_id": str, "asset_ids": list[str]}`.
Verify: `.venv/bin/python -m pytest tests/test_step_1.py::test_ingest_event_batch -v`

---

## T-1.10: Register `ingest_event_batch` as the production `FunctionTool`

Files: `src/capabilities/__init__.py`
Acceptance: Exports `all_function_tools: list[FunctionTool]` containing exactly one entry: `FunctionTool(ingest_event_batch)`. The FunctionTool's `.name` matches `"ingest_event_batch"`. Per D-021 — agent's tool surface is the 9-capability set; Step 1 establishes one of them. Later step branches will extend this list.
Verify: `.venv/bin/python -c "from src.capabilities import all_function_tools; names = [t.name for t in all_function_tools]; assert names == ['ingest_event_batch'], names; print('ok')"`

---

## T-1.11: Auto-wire production tools in `build_agent()`

Files: `src/agent.py`
Acceptance: `build_agent(extra_tools=None)` imports `all_function_tools` from `src.capabilities` and prepends them to the agent's `tools` list. `build_agent()` (no args) returns an agent with `ingest_event_batch` as its only registered tool. `build_agent(extra_tools=[echo_tool])` returns an agent with `ingest_event_batch` plus `echo_tool`. The D-019 enforcement test (`test_agent_does_not_expose_mcp_directly`) continues to pass.

System prompt: agent uses `prompts/v2/agent_system.md` (per Phase A item 6) — the loader reads `PROMPT_VERSION=v2` from `.env` or defaults to v2 in `src/prompt_loader.py`.

Verify:
- `.venv/bin/python -c "from src.agent import build_agent; a = build_agent(); print([t.name for t in a.tools])"` → `['ingest_event_batch']`
- `.venv/bin/python -m pytest tests/test_foundation.py -v` (5/5 still pass, including D-019 enforcement)

---

## T-1.12: Create eval test scaffolding

Files: `tests/evals/__init__.py`, `tests/evals/conftest.py`, `.gitignore` (add `tests/evals/_failures/`)
Acceptance: `tests/evals/conftest.py` exposes helpers reused across all capability evals:
- `build_runner_with_mock_db()` — returns `(runner, mock_client)`; monkeypatches `src.db.get_client` to return a `MagicMock` whose `call()` records invocations. The mock client surfaces a `.calls` attribute listing all `(tool_name, args)` invocations for assertion.
- `classify_part(part)` — returns `{"kind": "text|tool_call|tool_response", ...}` per the pattern in `spike/adk_event_capture.py`.
- `extract_tool_calls(events)` / `extract_tool_responses(events)` — convenience extractors.
- `dump_trace(events, label)` — writes structured trace to `tests/evals/_failures/{label}.json`; returns the path (for use in assertion messages).

Per `docs/plans/evaluation-strategy.md` Open Q #4 — `MongoMCPClient` mocking via `src.db.get_client` monkeypatch is the canonical seam.
Verify: `.venv/bin/python -c "from tests.evals.conftest import build_runner_with_mock_db, classify_part, extract_tool_calls, dump_trace; print('ok')"`

---

## T-1.13: Write trace eval — outcome-shaped (REWRITTEN per D-021)

Files: `tests/evals/test_step_1_trace.py`
Acceptance: Given the operator prompt *"We just finished Argentina vs France 3-2. Photos are in /tmp/wc-final/. Match started 19:00 UTC, finished ~20 min ago. Ingest this batch."*, the test asserts seven outcomes (exercising failure categories 1, 3, 5 from `docs/plans/evaluation-strategy.md`):

**(a) Capability selection** — agent called `ingest_event_batch` exactly once. Failure category 1.

**(b) Natural-language field extraction** — `event_metadata` passed to the capability has the correctly-extracted fields:
  - `home_team == "Argentina"`
  - `away_team == "France"`
  - `final_score` contains "3" and "2" (precise format flexible)
  - `outcome_type == "upset_victory"` (the agent's categorical judgment — France was favored)
  - `start_date` is ISO 8601 UTC string at 19:00 for today's date

Failure category 3 (the hardest assertion class — natural-language extraction quality).

**(c) MongoDB writes** — the mocked client recorded one `insert-many` on the `events` collection (with one document) and one `insert-many` on the `assets` collection (with all images from the operator's batch). Failure category 5.

**(d) Internal timeliness computation** — the event document in the mocked `insert-many` call has `timeliness` set to a non-null float in `[0.0, 1.0]`. (The agent doesn't compute this — the capability does internally. The assertion confirms it landed in the document.)

**(e) Reasoning text present** — at least one `text` part appears in the event stream before the tool call. Confirms the CoT directive from `prompts/v2/agent_system.md` is firing. Failure here is a layer-1 (framework) issue per `agentic-model.md`.

**(f) Terminal text after success** — agent emits a non-empty text turn *after* the tool returns, signaling completion. Confirms the v2 prompt's termination clause is working. The agent should not continue calling non-existent tools.

**(g) Failure diagnostics** — on any assertion failure, the full trace (tool calls + reasoning text + LLM responses) is dumped via `dump_trace()` and the path is included in the failure message.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_1_trace.py -v`

---

## T-1.14: Write pass-rate trace eval

Files: `tests/evals/test_step_1_trace.py` (extend)
Acceptance: A second test function runs the single-run eval **N=20 times** (configurable via `EVAL_REPEAT` env var, default 5 in CI). Asserts ≥ 19/20 runs pass all seven assertions (95% threshold per D-020). On failure, prints which assertion failed in which run and the pass-rate percentage.

The hardest assertions empirically are likely to be (b) `outcome_type == "upset_victory"` (categorical judgment) and (b) `start_date` correct format with inferred date. If these dip below threshold, the remediation playbook per `docs/plans/evaluation-strategy.md` applies: tighten system prompt → tighten capability docstring → consider adding examples → consider escalating model.

Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_1_trace.py::test_step_1_pass_rate -v`

---

## T-1.15: Full suite green

Files: (no new files)
Acceptance: All tests in `tests/` (including `tests/evals/`) pass with no errors. Full count: 5 foundation + 2 models + 3 errors + 1 timeliness + 3 step_1 (record_event, record_assets, ingest_event_batch) + 2 trace evals = **16 passing tests**.
Verify: `.venv/bin/python -m pytest tests/ -v`

---

## Tracking note

If any trace eval fails after the cheap remediation rungs (system-prompt tightening → docstring tightening → tool-surface change) have been tried, follow the playbook in `docs/plans/evaluation-strategy.md` § Remediation.

The pre-D-021 hybrid-wrapper escape hatch for hallucinated `timeliness` (D-019 Open Q #6) is no longer relevant — `compute_timeliness` is now internal to `ingest_event_batch` and the agent cannot hallucinate the value. Remediation now focuses on **natural-language field extraction quality** (specifically `outcome_type` categorization and `start_date` inference) — the hardest extraction judgments Step 1 makes.

Step 1's trace eval exercises failure categories **1, 3, 5** from the evaluation strategy. Strategy coherence (category 6) does not apply here — it lands when `propose_review_queue` ships in a later step.

---

## What changed from the pre-D-021 task list

For anyone reading the git history:

- **T-1.4 is new** — `PreconditionError` foundation class. Lands in Step 1 because the pattern is needed in `ingest_event_batch`'s input validation; all future capabilities reuse it.
- **T-1.7 and T-1.8 revised** — `record_event` and `record_assets` are now internal Python functions, not registered as `FunctionTool`s. The wrappers themselves are unchanged in behavior.
- **T-1.9 is new** — the `ingest_event_batch` capability that composes the three internal operations into one agent-facing tool. Lives in `src/capabilities/ingest.py` (new directory).
- **T-1.10 revised** — `all_function_tools` now lives in `src/capabilities/__init__.py` (was `src/db/__init__.py`) and contains one entry (`ingest_event_batch`) instead of three.
- **T-1.11 revised** — auto-wire imports from `src.capabilities`; agent's tool list shows one tool.
- **T-1.13 rewritten** — trace eval was sequencing-shaped (asserting `compute_timeliness < record_event < record_assets`); now outcome-shaped (asserting MongoDB state + natural-language extraction quality + terminal text).
- **Total test count: 16** (was 12). Adds: PreconditionError tests (3) + ingest_event_batch test (1). Subtracts: none — wrapper tests still in place.
- **Active prompt**: `prompts/v2/agent_system.md` (strategist framing) replaces v1.
