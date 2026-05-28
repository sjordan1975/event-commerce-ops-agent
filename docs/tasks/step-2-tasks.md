# Step 2 — Build Event Context: Task List

> Tasks T-2.1 through T-2.18 implement the `build_event_context` capability per `docs/plans/step-2-context.md`. One agent-facing FunctionTool composing four MongoDB reads, one direct-SDK Gemini call with `response_schema=EventNarrative`, and one persistence write that lands the narrative on the `events` document (per D-022). Five internal Python wrappers, one new capability-internal prompt, one new helper for the LLM call boundary. Tasks follow the plan's § Dependency order verbatim.

Prerequisites:
- Step 1 merged to `main` (16/16 tests green; 20/20 trace-eval pass rate per CLAUDE.md § Current Phase).
- Branch housekeeping commit landed on `step/2-context`: D-022 in `tracking.md`, `02-architecture.md` reflects `event_narrative` persistence + updated MCP call list, Planning Document Index Step 1 lines marked complete.
- `MongoMCPClient` + `get_client()` lazy singleton from Step 1 unchanged. `PreconditionError` from `src/errors.py` reused (no new error type this step).

Design decisions baked in (see `docs/plans/step-2-context.md` for rationale):
- One agent-facing `FunctionTool`: `build_event_context`, appended to `all_function_tools` in `src/capabilities/__init__.py`.
- Five internal Python wrappers (`get_event`, `find_past_events_by_outcome`, `update_event_narrative`, `aggregate_performance_for_events`, `find_players_for_teams`) — not exposed to the agent. First three extend `src/db/events.py`; the other two are new modules.
- One new capability-internal prompt at `prompts/v2/build_event_context.md` (loader reused — no loader change).
- `_run_narrative_llm` helper in `src/capabilities/context.py` isolates the direct `google.genai` SDK call; test seam for monkeypatching.
- `event_narrative` is persisted on the `events` document (per D-022) — not held only in agent state. Precondition for `propose_review_queue` (Step 5) becomes cheaply checkable.
- New env var `GEMINI_NARRATIVE_MODEL` separates narrative model from agent-loop model (`GEMINI_MODEL`). Default for both stays `gemini-2.5-flash-lite` — model swap is the last rung of the remediation ladder, not the first.
- Trace eval starts from a *pre-seeded* event in the mock DB — does not chain ingestion. Step 1's natural-language extraction is already covered by its own eval; combining muddies diagnosis.

---

## T-2.1: Add `Player` Pydantic model

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance: `Player` validates required fields (`player_id`, `name`, `nationality`, `team`, `position`, `notable_facts`, `career_milestones`, `commercial_signal`); `commercial_signal` is `Literal["high", "medium", "low"]`; `notable_facts` is `list[str]`. Shape mirrors the `player_context` JSON example in `docs/specs/02-architecture.md`. Test rejects an invalid `commercial_signal` value.
Verify: `.venv/bin/python -m pytest tests/test_models.py::test_player -v`

---

## T-2.2: Add `KeyFigure`, `HistoricalBaseline`, `EventNarrative` models

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance: All three models validate per the shapes in `docs/plans/step-2-context.md` § "The `EventNarrative` model (D-016 contract)":
- `KeyFigure`: `name`, `team`, `relevance`, `grounded_facts: list[str]`, `commercial_signal: Literal["high", "medium", "low"]`.
- `HistoricalBaseline`: `outcome_type`, `past_event_count: int`, `top_product_route: str | None`, `total_orders: int`, `total_impressions: int`, `notes: str`.
- `EventNarrative`: `event_id`, `narrative_angle`, `key_figures: list[KeyFigure]`, `commercial_timing`, `historical_baseline: HistoricalBaseline`.

Tests cover: happy-path construction, empty `key_figures` accepted (`list[KeyFigure]` with 0 items), `top_product_route=None` accepted, invalid `commercial_signal` on `KeyFigure` rejected.
Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k "key_figure or historical_baseline or event_narrative"`

---

## T-2.3: Add `event_narrative` field to `Event` model (per D-022)

Files: `src/models.py` (modify `Event`), `tests/test_models.py` (extend)
Acceptance: `Event.event_narrative: EventNarrative | None = None` (optional, defaults to `None`). Existing Event tests continue to pass (the field is additive and defaulted). New tests assert: (a) `Event` constructs with `event_narrative=None`; (b) `Event` constructs with a valid `EventNarrative` instance; (c) `Event` rejects a malformed `event_narrative` dict (Pydantic validates the nested shape at the Event boundary, per D-022).
Verify: `.venv/bin/python -m pytest tests/test_models.py::test_event -v`

---

## T-2.4: Extend conftest helpers

Files: `tests/conftest.py`
Acceptance: Two new helpers:
- `build_valid_player(**overrides) -> Player` — returns a valid `Player` instance with defaults matching the JSON example in `02-architecture.md` § `player_context`.
- `build_valid_event_narrative(**overrides) -> EventNarrative` — returns a valid `EventNarrative` instance with at least one `KeyFigure` and a populated `HistoricalBaseline`.

Both follow the same `**overrides` pattern as `build_valid_event` and `build_valid_asset` (Step 1).
Verify: `.venv/bin/python -c "from tests.conftest import build_valid_player, build_valid_event_narrative; from src.models import Player, EventNarrative; assert isinstance(build_valid_player(), Player); assert isinstance(build_valid_event_narrative(), EventNarrative); print('ok')"`

---

## T-2.5: Implement `get_event` wrapper (FIRST READ WRAPPER — pins the MCP read envelope parsing pattern)

Files: `src/db/events.py` (extend), `tests/test_step_2.py` (new file)
Acceptance: `get_event(event_id: str) -> Event | None` is async; calls `get_client().call("find", {"database": "event_commerce", "collection": "events", "filter": {"event_id": event_id}})`; parses the MongoDB MCP envelope and returns first-match as `Event` via `Event.model_validate(doc)`, or `None` if no match.

**This is the first read wrapper in the project** — Step 1's wrappers only call `insert-many` and discard the response, so the exact shape of MongoDB MCP `find` responses is established here. The implementer must (a) call the live MCP server once during implementation to confirm the envelope shape (is it a single JSON-encoded array in one text part, or one document per part, or something else?); (b) add a one-line comment in `src/db/events.py` next to the parse documenting the shape; (c) write a small parse helper (likely `_parse_find_response(envelope) -> list[dict]`) co-located in `src/db/events.py` (or `src/db/__init__.py` if T-2.6/T-2.8/T-2.9 will reuse — promote on second reuse, not first). T-2.6, T-2.8, T-2.9 must use the same parsing pattern.

Unit test monkeypatches `src.db.events.get_client` to return a `MagicMock` whose `call()` returns an envelope of the documented shape; asserts (a) the call args (`database`, `collection`, `filter` shape); (b) returns `Event` on match; (c) returns `None` on empty result.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py::test_get_event -v`

---

## T-2.6: Implement `find_past_events_by_outcome` wrapper

Files: `src/db/events.py` (extend), `tests/test_step_2.py` (extend)
Acceptance: `find_past_events_by_outcome(outcome_type: str, exclude_event_id: str) -> list[Event]` is async; calls `get_client().call("find", {"database": "event_commerce", "collection": "events", "filter": {"outcome_type": outcome_type, "event_id": {"$ne": exclude_event_id}}})`; returns the matches as `list[Event]` (empty list when no past events exist).
Unit test monkeypatches `src.db.events.get_client`; asserts call shape (including the `$ne` exclusion) and that returned list is parsed as `Event` instances.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py::test_find_past_events_by_outcome -v`

---

## T-2.7: Implement `update_event_narrative` wrapper

Files: `src/db/events.py` (extend), `tests/test_step_2.py` (extend)
Acceptance: `update_event_narrative(event_id: str, narrative: EventNarrative) -> None` is async; calls `get_client().call("update-many", {"database": "event_commerce", "collection": "events", "filter": {"event_id": event_id}, "update": {"$set": {"event_narrative": narrative.model_dump(mode="json")}}})`. The MongoDB MCP server exposes `update-many` but not `update-one`; filter is unique by `event_id`, so semantics collapse to a single-document update (per D-022). No return value.
Unit test monkeypatches `src.db.events.get_client`; asserts call shape — specifically the `update.$set.event_narrative` payload matches `narrative.model_dump(mode="json")`.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py::test_update_event_narrative -v`

---

## T-2.8: Implement `aggregate_performance_for_events` wrapper

Files: `src/db/performance.py` (new), `tests/test_step_2.py` (extend)
Acceptance: `aggregate_performance_for_events(event_ids: list[str]) -> dict` is async; calls `get_client().call("aggregate", {"database": "event_commerce", "collection": "performance", "pipeline": [...]})` with a pipeline that:
1. `$match` documents with `event_id` in `event_ids`.
2. `$lookup` against `assets` collection (local field `asset_id` → foreign field `asset_id`) to bring `product_route` onto each performance document. The `performance` schema (per `02-architecture.md` § `performance`) does **not** carry `product_route` — it lives on `assets` — so `$lookup` is the required join path, not an option.
3. `$unwind` the lookup result; `$group` by `product_route`, summing `metrics.shopify.orders` and `metrics.social.impressions`, counting docs.
4. `$sort` by total orders desc; take the top entry for `top_product_route`.

Returns: `{"past_event_count": int, "top_product_route": str | None, "total_orders": int, "total_impressions": int, "asset_count": int}`. When `event_ids` is empty or no matches found, returns `{"past_event_count": 0, "top_product_route": None, "total_orders": 0, "total_impressions": 0, "asset_count": 0}`. `past_event_count` equals `len(event_ids)` regardless of how many had performance docs.

Unit tests: (a) wrapper passes correct pipeline shape; (b) empty-result path returns zeroed baseline; (c) populated-result path parses envelope and surfaces the top product_route.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py -v -k aggregate_performance`

---

## T-2.9: Implement `find_players_for_teams` wrapper

Files: `src/db/player_context.py` (new), `tests/test_step_2.py` (extend)
Acceptance: `find_players_for_teams(home_team: str, away_team: str) -> list[Player]` is async; calls `get_client().call("find", {"database": "event_commerce", "collection": "player_context", "filter": {"team": {"$in": [home_team, away_team]}}})`; returns `list[Player]` (parsed via `Player.model_validate(doc)`). Returns empty list when no players seeded for either team.
Unit test monkeypatches `src.db.player_context.get_client`; asserts call shape and that results are parsed as `Player` instances.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py::test_find_players_for_teams -v`

---

## T-2.10: Write narrative prompt template

Files: `prompts/v2/build_event_context.md` (new)
Acceptance: File contains the prompt template per `docs/plans/step-2-context.md` § "Prompt template (load-bearing — eval asserts on its output structure)". The template uses Python `.format()`-style placeholders (not Jinja); placeholders include `{event.name}`, `{event.home_team}`, `{event.away_team}`, `{event.final_score}`, `{event.outcome_type}`, `{event.timeliness}`, `{event.location}`, `{cohort_summary}`, `{baseline.past_event_count}`, `{baseline.top_product_route}`, `{baseline.total_orders}`, `{baseline.total_impressions}`, `{player_block}`. The "do not invent facts" + "subset of notable_facts (verbatim)" framing is the load-bearing hallucination guard — both phrases must appear.

The prompt loader (`src/prompt_loader.py`) handles arbitrary names per CLAUDE.md, so no loader change is needed — `load_prompt("build_event_context")` resolves under `prompts/v2/`.

Verify: `.venv/bin/python -c "from src.prompt_loader import load_prompt; p = load_prompt('build_event_context'); assert 'do not invent facts' in p.lower() or 'do not invent' in p.lower(); assert 'verbatim' in p.lower(); print('ok')"`

---

## T-2.11: Implement `_run_narrative_llm` helper

Files: `src/capabilities/context.py` (new), `tests/test_step_2.py` (extend)
Acceptance: `_run_narrative_llm(prompt: str, schema: type[BaseModel]) -> BaseModel` (sync function — `google.genai`'s `generate_content` is the synchronous SDK; if the capability is async, it can run this via `asyncio.to_thread`). Body matches the pattern in `docs/plans/step-2-context.md` § "Internal-LLM-call pattern":
- Reads `GOOGLE_API_KEY` and `GEMINI_NARRATIVE_MODEL` (default `gemini-2.5-flash-lite`) from env.
- Calls `genai.Client(api_key=...).models.generate_content(model=..., contents=prompt, config=GenerateContentConfig(response_mime_type="application/json", response_schema=schema))`.
- Returns `schema.model_validate_json(response.text)`.

Private to the module (underscore prefix) — test seam is monkeypatching `src.capabilities.context._run_narrative_llm`.

Unit test mocks `genai.Client` at the import boundary (`src.capabilities.context.genai.Client`); asserts the call passes `model`, `contents`, and a `config` with `response_schema=EventNarrative`; asserts the return is the parsed schema instance.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py::test_run_narrative_llm -v`

---

## T-2.12: Implement `build_event_context` capability

Files: `src/capabilities/context.py` (extend), `tests/test_step_2.py` (extend)
Acceptance: `build_event_context(event_id: str) -> dict` is async. Behavior per `docs/plans/step-2-context.md` § "What the capability does internally":

1. `event = await get_event(event_id)` — if `None`, raise `PreconditionError(capability="build_event_context", context=event_id, missing={"event": "event not found; call ingest_event_batch first"})`.
2. `past_events = await find_past_events_by_outcome(event.outcome_type, exclude_event_id=event_id)`.
3. `baseline = await aggregate_performance_for_events([e.event_id for e in past_events])` — wrap as `HistoricalBaseline(outcome_type=event.outcome_type, ...)`.
4. `players = await find_players_for_teams(event.home_team, event.away_team)`.
5. Format prompt via `load_prompt("build_event_context").format(event=event, cohort_summary=..., baseline=baseline, player_block=...)`. When cohort or players are empty, prompt uses the "(no past events…)" / "(no seeded players…)" branches per the template.
6. `narrative = await asyncio.to_thread(_run_narrative_llm, prompt, EventNarrative)` — `_run_narrative_llm` is synchronous (per T-2.11 / plan), `build_event_context` is async, so the wrap is required (not optional). Returns the parsed `EventNarrative` instance.
7. `await update_event_narrative(event_id, narrative)` (per D-022).
8. `return narrative.model_dump(mode="json")`.

Tool docstring (load-bearing for the agent): per `docs/plans/step-2-context.md` § "Tool docstring (what the agent reads to plan)" — must include the line about being independent of `find_similar_assets` and `score_assets_with_vision` (order is the agent's call), and must name the downstream consumers (`propose_review_queue`, `draft_campaigns_for_queue`).

Unit tests cover:
- `test_build_event_context_raises_when_event_missing`: `get_event` returns `None` → `PreconditionError` with matching `capability`, `context`, `missing`.
- `test_build_event_context_orchestration`: mocks all four wrappers + `_run_narrative_llm`; asserts call order (event read → past events → performance → players → LLM → update); asserts returned dict matches `EventNarrative.model_dump(mode="json")` shape.
- `test_build_event_context_empty_cohort`: when `past_events == []`, baseline has `past_event_count=0`, `top_product_route=None`; LLM still called; the formatted prompt contains the empty-cohort branch text.
- `test_build_event_context_empty_players`: when `players == []`, the formatted prompt contains the empty-players branch text; capability still completes.

Each unit test monkeypatches per-module bindings (`src.db.events.get_client`, `src.db.performance.get_client`, `src.db.player_context.get_client`) and `src.capabilities.context._run_narrative_llm`.
Verify: `.venv/bin/python -m pytest tests/test_step_2.py -v -k build_event_context`

---

## T-2.13: Register `build_event_context` in `all_function_tools`

Files: `src/capabilities/__init__.py` (modify)
Acceptance: `all_function_tools` now contains exactly two entries: `FunctionTool(ingest_event_batch)` (from Step 1) and `FunctionTool(build_event_context)` (Step 2). Names: `["ingest_event_batch", "build_event_context"]`. Order is not load-bearing for ADK but keep it in capability-graph order (ingest → context).
Verify: `.venv/bin/python -c "from src.capabilities import all_function_tools; names = [t.name for t in all_function_tools]; assert names == ['ingest_event_batch', 'build_event_context'], names; print('ok')"`

---

## T-2.14: Extend eval scaffolding for multi-collection mock dispatch

Files: `tests/evals/conftest.py` (modify), `tests/evals/test_mock_dispatch.py` (new — smoke test)
Acceptance: `_MockMCPClient` (introduced in Step 1) is extended with a dispatch table keyed by `(tool_name, collection)` so tests can register expected reads explicitly per call shape. Specifically:
- `find` against `events` with filter by `event_id` returns the seeded event document.
- `find` against `events` with filter by `outcome_type` returns the seeded past-event cohort.
- `aggregate` against `performance` returns the seeded baseline pipeline result.
- `find` against `player_context` with filter by `team` returns the seeded player list.
- `update-many` against `events` setting `event_narrative` is recorded (no-op return; assertion target).

**Envelope shape (load-bearing for read-wrapper compatibility):** the Step 1 mock returned a literal `{"content": [{"type": "text", "text": "ok"}]}` for every call — fine for `insert-many` (response discarded) but would crash Step 2's read wrappers, which JSON-parse documents out of the envelope (pattern pinned by T-2.5). The extended mock must encode each dispatched read result as JSON in the `text` field of the envelope, matching the shape T-2.5 documents from the real MongoDB MCP server. Test code that registers seeded reads passes Python dicts/lists; the mock serializes them with `json.dumps` before returning the envelope.

The existing `src.db.events.get_client` and `src.db.assets.get_client` patch surfaces extend to two new module bindings: `src.db.performance.get_client` and `src.db.player_context.get_client`. `build_runner_with_mock_db()` returns the same mock client wired into all four modules so a single recorded `.calls` list captures every wrapper call across the capability surface.

Smoke test (not a trace eval; lives at `tests/evals/test_mock_dispatch.py`): registers one seeded read of each shape, instantiates the mock client directly (no agent runner needed), invokes each Step 2 wrapper, asserts the wrapper returns the correctly-parsed Pydantic models from the seeded data, and asserts the `update-many` call shape is captured verbatim in `.calls`.
Verify: `.venv/bin/python -m pytest tests/evals/test_mock_dispatch.py -v`

---

## T-2.15: Write outcome-shaped trace eval (single run)

Files: `tests/evals/test_step_2_trace.py` (new)
Acceptance: Given a pre-seeded event in the mock DB (Argentina vs France; `event_id="evt-demo-1"`; `outcome_type="upset_victory"`; player_context seeded for both teams; 3 past events of the same outcome_type with performance data) and the operator prompt *"The event with id `evt-demo-1` has been ingested. Build context for it."*, the test asserts eight outcomes per `docs/plans/step-2-context.md` § Verification checkpoints row 6:

(a) **Capability selection** — agent called `build_event_context` exactly once.
(b) **No hallucinated capability calls** — agent did NOT call `ingest_event_batch` (the event is already ingested per the operator prompt). Failure category 1.
(c) **Tool argument** — `event_id="evt-demo-1"`. Failure category 3.
(d) **MongoDB read shapes** — mock client `.calls` includes: `find` on `events` by `event_id`, `find` on `events` by `outcome_type`, `aggregate` on `performance`, `find` on `player_context` by `team`. Failure category 5 (end-state of reads).
(e) **Persistence write** — mock client `.calls` includes one `update-many` on `events` with `update.$set.event_narrative` populated (filter unique by `event_id`). Per D-022.
(f) **Return shape** — the returned dict has the four `EventNarrative` top-level keys: `narrative_angle`, `key_figures`, `commercial_timing`, `historical_baseline`. Failure category 5 (end-state of return).
(g) **Hallucination guard** — for every `key_figure` in the returned `key_figures`, every entry in `grounded_facts` is a literal substring of that player's `notable_facts` (from the seeded `player_context`). Failure category 4 (tool-output handling — the LLM-inside-tool could fabricate, this asserts it does not).
(h) **Reasoning text present** — at least one `text` event-part appears before the tool call (CoT directive working).

On any assertion failure: `dump_trace()` writes the full trace under `tests/evals/_failures/step_2_trace_<timestamp>.json` and the path is included in the failure message.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_2_trace.py::test_step_2_single_run -v`

---

## T-2.16: Write pass-rate trace eval (N=20)

Files: `tests/evals/test_step_2_trace.py` (extend)
Acceptance: A second test function runs the single-run eval N=20 times (configurable via `EVAL_REPEAT` env var, default 5 in CI). Asserts ≥ 19/20 runs pass all eight assertions (95% threshold per D-020). On failure, prints which assertion failed in which run and the per-assertion pass-rate.

The hardest assertion empirically is expected to be (g) the hallucination guard — the LLM's narrative composition is the only assertion target with non-deterministic creative latitude. If pass rate dips below threshold, follow the remediation playbook per `docs/plans/evaluation-strategy.md`: tighten prompt language → tighten capability docstring → tighten schema constraint (e.g., add post-validation in `build_event_context` that filters `grounded_facts` to the verbatim-substring subset) → swap `GEMINI_NARRATIVE_MODEL` to `gemini-2.5-flash` as the last rung.

The MVP-acceptability escape hatch is explicitly forbidden by CLAUDE.md (and the user's standing feedback memory) — climb the ladder fully before declaring done.

Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_2_trace.py::test_step_2_pass_rate -v`

---

## T-2.17: Document `GEMINI_NARRATIVE_MODEL` in `.env.example`

Files: `.env.example` (modify)
Acceptance: New line added documenting `GEMINI_NARRATIVE_MODEL` env var with default value `gemini-2.5-flash-lite` and a brief comment indicating it is the model used by the internal narrative LLM call in `build_event_context` and can be swapped independently of `GEMINI_MODEL` (the agent-loop model).
Verify: `grep -q "GEMINI_NARRATIVE_MODEL" .env.example && echo "ok"`

---

## T-2.18: Full suite green

Files: (no new files)
Acceptance: All tests in `tests/` (including `tests/evals/`) pass with no errors. Includes:
- Step 1 carry-forward: 16 tests (5 foundation + 2 models + 3 errors + 1 timeliness + 3 step_1 + 2 trace evals).
- Step 2 additions: ~19 tests (1 Player model + 3 narrative-type models + 3 Event.event_narrative scenarios + 5 wrappers + 4 capability scenarios + 1 mock-dispatch smoke + 2 trace evals — single-run + pass-rate).

**Approximate total after Step 2: ~35 passing tests.** (Approximate because conftest helper test counts depend on how `-k` filters break individual cases — the canonical anchor is "no failures, no errors, pass-rate gate ≥ 19/20".)

Then run the pass-rate gate (`EVAL_REPEAT=20`) — must hit ≥ 19/20.

Verify:
- `.venv/bin/python -m pytest tests/ -v` (full unit + single-run eval green)
- `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_2_trace.py::test_step_2_pass_rate -v`

---

## Tracking note

If trace eval pass-rate dips below the 95% threshold, follow the remediation ladder in `docs/plans/evaluation-strategy.md` § Remediation. The cheap rungs (prompt tightening → docstring tightening → schema constraint → hybrid post-validation in the wrapper) must be tried before the model swap (`GEMINI_NARRATIVE_MODEL` → `gemini-2.5-flash`). Per CLAUDE.md and the standing feedback rule, "acceptable for MVP" is not a valid stopping point with cheaper rungs untried.

Step 2's trace eval exercises failure categories **1, 3, 4, 5** per `docs/plans/evaluation-strategy.md`: tool selection (a, b), tool arguments (c), tool-output handling (g — the hallucination case is category 4), end-state (d, e, f). Strategy coherence (category 6) does not apply here — it lands when `propose_review_queue` ships in Step 5.

Per `docs/plans/workflow.md` Phase 6, advisor consultation is required before declaring Step 2 done — independent read on whether the implementation matches the plan, whether the eval exercises what it claims to, and whether anything was quietly cut to make tests pass. Commit before the advisor call so the deliverable is durable if the session ends mid-call.
