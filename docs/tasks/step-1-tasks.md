# Step 1 — Event Ingestion: Task List

Prerequisite: Step 0 foundation + Step 0.5 refactor merged to `main`. `MongoMCPClient` exists at `src/db/client.py`. `build_agent()` is a pass-through shell. 5/5 foundation tests passing.

Design decisions baked in (see `docs/plans/step-1-event-ingestion.md` for rationale):
- Lazy MongoDB MCP singleton via `get_client()` in `src/db/__init__.py`.
- FunctionTools registered in `src/db/__init__.py` as `all_function_tools`.
- `build_agent()` auto-wires `all_function_tools` from `src/db`.

---

## T-1.1: Create `Event` Pydantic model

Files: `src/models.py`, `tests/test_models.py`
Acceptance: `Event` validates required fields (`event_id`, `name`, `home_team`, `away_team`, `location`, `start_date`, `final_score`, `outcome_type`, `timeliness`, `ingested_at`); rejects unknown `outcome_type` (must be one of: `upset_victory`, `extra_time_win`, `expected_win`, `draw`); `timeliness` must be a float in `[0.0, 1.0]`.
Verify: `.venv/bin/python -m pytest tests/test_models.py::test_event -v`

---

## T-1.2: Create `Asset` Pydantic model

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance: `Asset` validates required fields (`asset_id`, `event_id`, `content_url`, `status`, `upload_date`); nullable fields (`product_route`, `queue_type`, `embedding`, `scores`, `campaign_id`) default to `None`; `status` defaults to `"ingested"`.
Verify: `.venv/bin/python -m pytest tests/test_models.py::test_asset -v`

---

## T-1.3: Update conftest helpers to return Pydantic models

Files: `tests/conftest.py`
Acceptance: `build_valid_event(**overrides)` returns an `Event` instance; `build_valid_asset(**overrides)` returns an `Asset` instance. Default field values unchanged from current dict form. Carried forward from `docs/plans/step-0.5-refactor.md` § 2.
Verify: `.venv/bin/python -c "from tests.conftest import build_valid_event, build_valid_asset; from src.models import Event, Asset; assert isinstance(build_valid_event(), Event); assert isinstance(build_valid_asset(), Asset); print('ok')"`

---

## T-1.4: Create timeliness calculator

Files: `src/timeliness.py`, `tests/test_timeliness.py`
Acceptance: `compute_timeliness(outcome_type: str, kickoff_utc: str) -> dict` returns `{"timeliness": <float>, "outcome_type": <str>}` per the formula `base_score × 0.5^(hours_since_kickoff / 4)`. Base scores: `upset_victory=0.95`, `extra_time_win=0.85`, `expected_win=0.60`, `draw=0.40`. 0h → base score; 4h → base/2; 8h → base/4. Raises `ValueError` for unknown `outcome_type`. Accepts ISO 8601 string for `kickoff_utc` (with `Z` suffix or `+00:00`).
Verify: `.venv/bin/python -m pytest tests/test_timeliness.py -v`

---

## T-1.5: Add lazy `get_client()` accessor

Files: `src/db/__init__.py`
Acceptance: `get_client()` returns a module-level lazy singleton `MongoMCPClient` (`_client: MongoMCPClient | None = None`; instantiated on first call). Repeat calls return the same instance. Does not read `MONGODB_URI` at module import time.
Verify: `.venv/bin/python -c "from src.db import get_client; c1 = get_client(); c2 = get_client(); assert c1 is c2; print('ok')"` (requires `MONGODB_URI` in `.env`)

---

## T-1.6: Implement `record_event` wrapper

Files: `src/db/events.py`, `tests/test_step_1.py`
Acceptance: `record_event(event: Event) -> str` is async; validates the Pydantic `Event`; calls `get_client().call("insert-many", {"database": "event_commerce", "collection": "events", "documents": [event.model_dump(mode="json")]})`; returns `event.event_id`. Docstring: *"Records an event in the events collection. Returns the event_id. The event must include a `timeliness` value — call compute_timeliness first and pass the returned float into event.timeliness."*
Unit test monkeypatches `src.db.get_client` to return a `MagicMock`; asserts the wrapper passes correct collection name and documents list.
Verify: `.venv/bin/python -m pytest tests/test_step_1.py::test_record_event -v`

---

## T-1.7: Implement `record_assets` wrapper

Files: `src/db/assets.py`, `tests/test_step_1.py` (extend)
Acceptance: `record_assets(event_id: str, assets: list[Asset]) -> list[str]` is async; Pydantic-validates each asset; sets `status="ingested"` if not already set; calls `get_client().call("insert-many", {"database": "event_commerce", "collection": "assets", "documents": [a.model_dump(mode="json") for a in assets]})`; returns `[a.asset_id for a in assets]` in input order. Docstring: *"Bulk-records image assets for an event. Returns asset_ids in input order. Call this after record_event; pass the returned event_id from that call. Each asset is stored with status='ingested' by default."*
Unit test monkeypatches `src.db.get_client`; asserts batch shape and order preservation.
Verify: `.venv/bin/python -m pytest tests/test_step_1.py::test_record_assets -v`

---

## T-1.8: Register `all_function_tools` in `src/db/__init__.py`

Files: `src/db/__init__.py` (extend)
Acceptance: Exports `all_function_tools: list[FunctionTool]` containing `FunctionTool(compute_timeliness)`, `FunctionTool(record_event)`, `FunctionTool(record_assets)`. Each FunctionTool's `.name` matches the underlying callable's `__name__`.
Verify: `.venv/bin/python -c "from src.db import all_function_tools; names = [t.name for t in all_function_tools]; assert names == ['compute_timeliness', 'record_event', 'record_assets'], names; print('ok')"`

---

## T-1.9: Auto-wire production tools in `build_agent()`

Files: `src/agent.py`
Acceptance: `build_agent(extra_tools=None)` imports `all_function_tools` from `src.db` and prepends them to the agent's `tools` list. `build_agent()` (no args) returns an agent with the three Step 1 FunctionTools. `build_agent(extra_tools=[echo_tool])` returns an agent with the three Step 1 tools plus `echo_tool`. The D-019 enforcement test (`test_agent_does_not_expose_mcp_directly`) continues to pass.
Verify:
- `.venv/bin/python -c "from src.agent import build_agent; a = build_agent(); print([t.name for t in a.tools])"` → `['compute_timeliness', 'record_event', 'record_assets']`
- `.venv/bin/python -m pytest tests/test_foundation.py -v` (5/5 still pass)

---

## T-1.10: Create eval test scaffolding

Files: `tests/evals/__init__.py`, `tests/evals/conftest.py`, `.gitignore` (add `tests/evals/_failures/`)
Acceptance: `tests/evals/conftest.py` exposes helpers reused across all step evals:
- `build_runner_with_mock_db()` — returns `(runner, captured_calls)`; monkeypatches `src.db.get_client` to return a `MagicMock` whose `call()` records invocations.
- `classify_part(part)` — returns `{"kind": "text|tool_call|tool_response", ...}` per the pattern in `spike/adk_event_capture.py`.
- `extract_tool_calls(events)` / `extract_tool_responses(events)` — convenience extractors.
- `dump_trace(events, label)` — writes structured trace to `tests/evals/_failures/{label}.json`; returns the path (for use in assertion messages).
Verify: `.venv/bin/python -c "from tests.evals.conftest import build_runner_with_mock_db, classify_part, extract_tool_calls, dump_trace; print('ok')"`

---

## T-1.11: Write single-run trace eval

Files: `tests/evals/test_step_1_trace.py`
Acceptance: Given the prompt *"We just finished Argentina vs France 3–2. Photos are in /tmp/wc-final/. Match started 19:00 UTC, finished ~20 min ago. Get them into the system."*, the test asserts:
(a) agent calls `compute_timeliness` **before** `record_event`;
(b) `timeliness` value passed to `record_event` **equals** the value returned by `compute_timeliness` (no hallucination);
(c) `record_event` called exactly once;
(d) `record_assets` called exactly once with all images and `status="ingested"`;
(e) intermediate reasoning text is present for each tool call (CoT directive firing);
(f) on assertion failure, the full trace (tool_calls + tool_responses + reasoning text) is dumped via `dump_trace()` and the path included in the failure message.
Verify: `.venv/bin/python -m pytest tests/evals/test_step_1_trace.py -v`

---

## T-1.12: Write pass-rate trace eval

Files: `tests/evals/test_step_1_trace.py` (extend)
Acceptance: A second test function runs the single-run eval **N=20 times** (configurable via `EVAL_REPEAT` env var, default 5 in CI). Asserts ≥ 19/20 runs pass all six assertions (95% threshold per D-020). On failure, prints which assertion failed in which run and the pass-rate percentage.
Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_1_trace.py::test_step_1_pass_rate -v`

---

## T-1.13: Full suite green

Files: (no new files)
Acceptance: All tests in `tests/` (including `tests/evals/`) pass with no errors. Full count: 5 foundation + 2 models + 1 timeliness + 2 step_1 wrappers + 2 trace evals = **12 passing tests**.
Verify: `.venv/bin/python -m pytest tests/ -v`

---

## Tracking note

If any trace eval fails after the cheap remediation rungs (system-prompt tightening → docstring tightening → tool-surface change) have been tried, follow the playbook in `docs/plans/evaluation-strategy.md` § Remediation. Falling back to `record_event` as a hybrid wrapper (defends against hallucinated `timeliness`) is the D-019 Q#6 escape hatch — do not silently absorb the failure.
