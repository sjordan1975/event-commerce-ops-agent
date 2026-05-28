# Step 2 — Build Event Context: Implementation Plan

> Step 2 delivers the `build_event_context` capability — one agent-facing tool that aggregates the event record, historical performance baseline, and player biographical facts, then has Gemini produce a typed `EventNarrative` consumed by `propose_review_queue` (capability 5) and `draft_campaigns_for_queue` (capability 6). First "computational + LLM" capability; sets the pattern for the internal-LLM-call shape that Step 4 (Vision) and Step 5 (drafting) will reuse. Operates per D-021's capability-surface and enforced-vs-emergent split: pre-condition is "event exists"; ordering vs. `find_similar_assets` / `score_assets_with_vision` is the agent's call.

## What this capability delivers

The agent calls `build_event_context(event_id)` for an ingested event. The capability internally:

1. Reads the event document (`PreconditionError` if not found)
2. Reads past events with the same `outcome_type` (historical cohort)
3. Aggregates performance metrics for that cohort to derive a baseline (top product route, average orders/impressions)
4. Reads `player_context` for both teams (plain name match against `events.home_team` / `events.away_team`)
5. Calls Gemini with a structured prompt + the four data inputs above + an `EventNarrative` response schema
6. Persists the resulting narrative onto the `events` document (`event_narrative` field)
7. Returns the narrative as a dict to agent state

Returns the `EventNarrative` payload to agent state. Consumed downstream by:
- `propose_review_queue` (capability 5) — narrative is one of its four hard preconditions per D-021
- `draft_campaigns_for_queue` (capability 6) — narrative is copy substrate per D-016

Trace eval at `tests/evals/test_step_2_trace.py` satisfies D-020's per-capability requirement (pass rate ≥ 95% across 20 reps is the ship gate).

Prerequisite: Step 1 ingestion is merged to `main`. `ingest_event_batch` is registered. `MongoMCPClient`, `PreconditionError`, models, error format are stable.

---

## The capability surface (D-019 + D-021)

| Tool | Type | Why |
| --- | --- | --- |
| `build_event_context` | FunctionTool (agent-facing capability) | The one Step 2 agent-facing tool. Internally orchestrates four internal reads, one LLM call, and one event-document update. No raw MongoDB on the agent surface. |

Internal Python wrappers added this step (none are `FunctionTool`s):

| Wrapper | File | Purpose |
| --- | --- | --- |
| `get_event(event_id)` | `src/db/events.py` (extension) | Plain `find` on `events` — used by Step 2 and reused by Steps 4–9. Returns `Event` or `None`. |
| `find_past_events_by_outcome(outcome_type, exclude_event_id)` | `src/db/events.py` (extension) | Returns past events that share `outcome_type` — the historical cohort. |
| `aggregate_performance_for_events(event_ids)` | `src/db/performance.py` (new file) | Wraps `performance.aggregate`; groups metrics by `product_route`; returns `{top_product_route, total_orders, total_impressions, asset_count}`. |
| `find_players_for_teams(home_team, away_team)` | `src/db/player_context.py` (new file) | Wraps `player_context.find` with `{team: {$in: [home, away]}}`; returns `list[Player]`. |
| `update_event_narrative(event_id, narrative)` | `src/db/events.py` (extension) | Wraps `update-many` to set `event_narrative` on the events doc. |

LLM call:

| Helper | File | Purpose |
| --- | --- | --- |
| `_run_narrative_llm(prompt, schema)` | `src/capabilities/context.py` (private module function) | Wraps a single `google.genai` `generate_content` call with `response_schema=EventNarrative`. Testable via monkeypatch on `src.capabilities.context._run_narrative_llm`. |

Per D-019, `MongoMCPClient` is still the only MongoDB programmatic client; new wrappers call `get_client().call(...)` exactly like Step 1's wrappers. Raw MongoDB MCP tools remain unexposed. D-019 enforcement test on `main` continues to pass.

---

## What the LLM does in this capability

This is the first capability with an LLM call *inside* it. Two distinct LLM invocations occur during a Step 2 turn — they should not be conflated:

1. **The agent's reasoning + tool-call decision (outside the capability).** The single ADK `LlmAgent` reads the system prompt, the `build_event_context` docstring, and the operator transcript, then decides to call the tool with one argument: `event_id`. This is the same loop Step 1 exercised. Per the CoT directive in `prompts/v2/agent_system.md`, the agent emits a one-sentence rationale before the call.

2. **The narrative-generation LLM call (inside the capability).** After the four MongoDB reads complete, the capability calls Gemini directly via `google.genai` with: a fixed prompt template, the structured data payload, and `response_schema=EventNarrative`. The model returns a Pydantic-validated `EventNarrative` object. The agent never sees this call as a separate event in the trace — from the agent's view it is a deterministic-looking tool return.

The narrative-generation call is the bulk of LLM work in Step 2. It is **bounded reasoning** (per `agentic-model.md`): the model is composing a structured artifact from grounded inputs, not making a strategic decision. The schema constrains output shape; the prompt constrains what each field means.

### Internal-LLM-call pattern (set here; reused by Step 4 and Step 5)

```python
def _run_narrative_llm(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Single-call Gemini generate_content with structured output. Internal."""
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=os.environ.get("GEMINI_NARRATIVE_MODEL", "gemini-2.5-flash"),
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    return schema.model_validate_json(response.text)
```

Rationale:
- **Direct `google.genai` over an ADK sub-runner.** The narrative call has no tools to call; an ADK runner would be overkill. Direct SDK matches what `scripts/seed_mongodb.py` already uses.
- **Schema-bound output.** `response_schema=EventNarrative` makes parsing failures impossible at the deserialization level — the model is forced into the shape, or `model_validate_json` raises and we surface the failure.
- **Model env-var separated from agent model.** `GEMINI_NARRATIVE_MODEL` (default `gemini-2.5-flash-lite` — same as `GEMINI_MODEL`) is decoupled from `GEMINI_MODEL` so the narrative model can be swapped without touching the agent loop. The separation is structural; the *default* matches the agent — model swap is the last rung of the remediation ladder, not the first. If trace evals fail the grounded-facts assertion or narrative-quality bar, climb the ladder (prompt → schema → wrapper validation) before bumping this env var.
- **Testable boundary.** Unit tests monkeypatch `src.capabilities.context._run_narrative_llm` to return a hand-built `EventNarrative`; trace evals leave it real.

This pattern carries forward: Step 4 (`score_assets_with_vision`) and Step 6 (`draft_campaigns_for_queue`) get their own `_run_*_llm` helpers in their own capability modules. (Step 5 — `propose_review_queue` — is the strategic decision; its LLM "call" is the agent's own reasoning, not an internal helper.) We do not extract a shared `llm_utils.py` yet — premature; reach for it only if the third instance shares more than three lines with the first two.

---

## What the capability does internally

```text
build_event_context(event_id: str) → dict (EventNarrative payload)
    1. get_event(event_id) → Event or None
         raises PreconditionError("event not found; call ingest_event_batch first")
    2. find_past_events_by_outcome(event.outcome_type, exclude=event_id) → list[Event]
    3. aggregate_performance_for_events([e.event_id for e in past_events]) → baseline dict
         (returns empty baseline if no past events — narrative_angle still composed; baseline.notes records absence)
    4. find_players_for_teams(event.home_team, event.away_team) → list[Player]
    5. _run_narrative_llm(prompt_from_template(event, past_events, baseline, players),
                          schema=EventNarrative) → EventNarrative
    6. update_event_narrative(event_id, narrative)
    7. return narrative.model_dump()
```

Step 1 (event read) is the only hard precondition. Steps 2–4 (cohort, performance, players) tolerate empty results — narrative is still constructable for a brand-new outcome type or a team with no seeded players. The LLM is given the empty state explicitly in the prompt so it does not hallucinate facts.

Order of steps 1–4 inside the capability is mechanically required (event must be read first to know `outcome_type`, `home_team`, `away_team`). They are not parallelized — sequential is fine; each is sub-100ms in practice and the round-trip dominates anyway.

---

## The `EventNarrative` model (D-016 contract)

The shape is a contract with two downstream consumers (`propose_review_queue`, `draft_campaigns_for_queue`). Specifying it concretely here, not deferring:

```python
class KeyFigure(BaseModel):
    name: str
    team: str
    relevance: str                # one-line "why this player matters for this event"
    grounded_facts: list[str]     # subset of player_context.notable_facts; verbatim
    commercial_signal: Literal["high", "medium", "low"]

class HistoricalBaseline(BaseModel):
    outcome_type: str
    past_event_count: int
    top_product_route: str | None       # e.g. "poster"; None when cohort empty
    total_orders: int
    total_impressions: int
    notes: str                          # human-readable summary; "no historical data yet" when empty

class EventNarrative(BaseModel):
    event_id: str
    narrative_angle: str                # e.g. "upset victory: France's title defense ends"
    key_figures: list[KeyFigure]        # 1–4 players; selected by LLM from full squad lists
    commercial_timing: str              # e.g. "aggressive — timeliness 0.95, ~4h window remaining"
    historical_baseline: HistoricalBaseline
```

`commercial_signal` on `KeyFigure` is copied verbatim from `player_context.commercial_signal` (set at seed time per D-016) — not re-derived by the LLM. The grounded_facts list is required to be a subset of the player's `notable_facts` — the prompt instructs the LLM to copy facts, not invent them. Eval asserts this (substring match).

`narrative_angle` is freeform single-sentence; the LLM composes from outcome_type + score + key player presence. `commercial_timing` is freeform single-sentence grounded in `event.timeliness`.

`event_id` is duplicated in the model to make the persisted document self-identifying (it lives on the `events` doc under `event_narrative`, so the parent doc already has it; the duplicate is for downstream consumers that might receive only the narrative payload).

---

## Persistence: `event_narrative` field on `events`

After the LLM returns, the capability writes `event_narrative` onto the events document:

```text
events.update-many({event_id: <id>}, {$set: {event_narrative: <serialized EventNarrative>}})
```

This makes the narrative a checkable precondition for capability 5. `propose_review_queue` will (in a later step) do:

```python
event = get_event(event_id)
if event.event_narrative is None:
    raise PreconditionError(
        capability="propose_review_queue",
        context=event_id,
        missing={"event_narrative": "call build_event_context first"},
    )
```

The alternative — agent passes the narrative dict as an argument to `propose_review_queue` — was considered and rejected: it puts a multi-hundred-token payload through the agent's tool-call surface every time queue assembly runs, increases token cost, and makes the agent responsible for not losing the artifact across reasoning turns. Persistence on the events doc is cheap, makes preconditions trivially checkable, and survives session reset.

Update to `Event` Pydantic model: `event_narrative: EventNarrative | None = None` (optional; populated by Step 2). `EventNarrative` lives in the same `src/models.py` file, so no import cycle — type the field honestly and let Pydantic validate at read/write boundaries. Downstream consumers receive a validated `EventNarrative` directly.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `EventNarrative` model + nested types | `src/models.py` (extension) | `KeyFigure`, `HistoricalBaseline`, `EventNarrative`; validated as Gemini's response schema |
| 2 | `Player` model | `src/models.py` (extension) | Shape returned by `find_players_for_teams`; matches the `player_context` document |
| 3 | `Event.event_narrative` field | `src/models.py` (modification) | New optional `EventNarrative | None` field; serialized on insert/update; validated by Pydantic at the Event boundary |
| 4 | `get_event` wrapper | `src/db/events.py` (extension) | `find` for one event by `event_id`; returns `Event` or `None` |
| 5 | `find_past_events_by_outcome` wrapper | `src/db/events.py` (extension) | Cohort lookup by `outcome_type` |
| 6 | `update_event_narrative` wrapper | `src/db/events.py` (extension) | Persists the narrative onto the events doc |
| 7 | `aggregate_performance_for_events` wrapper | `src/db/performance.py` (new) | Baseline aggregation; returns dict with `top_product_route`, totals, count |
| 8 | `find_players_for_teams` wrapper | `src/db/player_context.py` (new) | Plain name match on `team` field |
| 9 | Narrative prompt template | `prompts/v2/build_event_context.md` (new) | The fixed prompt the capability formats with event/cohort/players/baseline data; lives in `prompts/` per CLAUDE.md's prompt-loader convention |
| 10 | `_run_narrative_llm` helper | `src/capabilities/context.py` (new module, private function) | Single `google.genai` call with structured output; testable via monkeypatch |
| 11 | `build_event_context` capability | `src/capabilities/context.py` (new module) | The one agent-facing tool; orchestrates 4 reads + LLM + 1 write |
| 12 | FunctionTool registration | `src/capabilities/__init__.py` (modification) | Append `FunctionTool(build_event_context)` to `all_function_tools` |
| 13 | Tests — unit | `tests/test_models.py` (extension), `tests/test_step_2.py` (new) | Models, wrappers, capability orchestration with mocked LLM and mocked client |
| 14 | Tests — trace eval | `tests/evals/test_step_2_trace.py` (new) | Outcome-shaped trace eval (single-run + N=20 repeat) |
| 15 | Eval conftest extension | `tests/evals/conftest.py` (modification) | `build_runner_with_mock_db` extended to seed event/players/performance reads; LLM left real |

`prompts/v2/build_event_context.md` is a *capability-internal* prompt, distinct from `prompts/v2/agent_system.md`. Both live under `prompts/v2/`; the loader's `load_prompt(name)` already handles arbitrary names. No loader change needed.

---

## Prompt template (load-bearing — eval asserts on its output structure)

`prompts/v2/build_event_context.md` is a single template the capability formats with four data inputs. The shape (Python-side substitution, not Jinja — keep it simple):

```text
You are composing a structured narrative for a sports event.
Output JSON matching the EventNarrative schema. Do not invent facts.
Use player facts only if they appear verbatim in the player_context list below.

EVENT
- name: {event.name}
- home_team: {event.home_team}
- away_team: {event.away_team}
- final_score: {event.final_score}
- outcome_type: {event.outcome_type}
- timeliness: {event.timeliness}
- location: {event.location or "(unspecified)"}

HISTORICAL COHORT (past events with outcome_type={event.outcome_type})
{cohort_summary or "(no past events of this outcome_type — historical_baseline.notes should say so)"}

PERFORMANCE BASELINE FOR COHORT
- past_event_count: {baseline.past_event_count}
- top_product_route: {baseline.top_product_route}
- total_orders: {baseline.total_orders}
- total_impressions: {baseline.total_impressions}

PLAYER CONTEXT (full squad lists; pick 1–4 narratively significant figures)
{player_block or "(no seeded players for these teams — key_figures should be empty)"}

REQUIREMENTS
- narrative_angle: one sentence, grounded in outcome_type + score + key player presence.
- key_figures: 1–4 players from PLAYER CONTEXT above. For each, grounded_facts must be
  a subset of the player's notable_facts (verbatim). commercial_signal must be the player's
  player_context.commercial_signal value, copied as-is.
- commercial_timing: one sentence, grounded in event.timeliness; describe the window urgency.
- historical_baseline: copy the values above into the schema; notes is one sentence summarizing.

If a section is empty (no cohort, no players), say so in the relevant field — do not fabricate.
```

The "do not invent facts" + "subset of notable_facts (verbatim)" framing is the hallucination guard. Eval asserts every `grounded_facts` entry appears in the corresponding player's `notable_facts` list.

---

## Dependency order

1. **Models** (`src/models.py`) — `Player`, `KeyFigure`, `HistoricalBaseline`, `EventNarrative`; modify `Event` to add `event_narrative: dict | None = None`
2. **Update conftest helpers** (`tests/conftest.py`) — `build_valid_player()`, `build_valid_event_narrative()` for reuse across tests
3. **`get_event` + `find_past_events_by_outcome` + `update_event_narrative`** (`src/db/events.py` extensions) — testable independently via monkeypatched client
4. **`aggregate_performance_for_events`** (`src/db/performance.py`, new) — same pattern
5. **`find_players_for_teams`** (`src/db/player_context.py`, new) — same pattern
6. **Prompt template** (`prompts/v2/build_event_context.md`) — fixed text; format-string interpolation only
7. **`_run_narrative_llm`** (`src/capabilities/context.py`) — small helper; unit-tested independently with a mocked `genai.Client`
8. **`build_event_context`** (`src/capabilities/context.py`) — composes 4 reads + LLM + 1 write; raises `PreconditionError` on missing event; unit test mocks both `get_client` (per-module bindings) and `_run_narrative_llm`
9. **FunctionTool registration** (`src/capabilities/__init__.py`) — append `FunctionTool(build_event_context)` to `all_function_tools`
10. **Trace eval scaffolding extension** (`tests/evals/conftest.py`) — extend `_MockMCPClient` to return seeded read results for `find` calls on `events`, `player_context`, `performance` (call-shape-discriminated); existing patch surface (`src.db.events.get_client`, `src.db.assets.get_client`) extends to new modules (`src.db.performance.get_client`, `src.db.player_context.get_client`)
11. **Trace eval — single run** (`tests/evals/test_step_2_trace.py`) — outcome-shaped assertions per the verification table below
12. **Trace eval — pass rate** — N=20 repetition harness; ≥ 95% threshold per D-020

---

## Tool docstring (what the agent reads to plan)

```python
async def build_event_context(event_id: str) -> dict:
    """Builds a structured narrative for an ingested event.

    Aggregates the event record, the historical performance baseline for events
    of the same outcome_type, and player biographical facts from player_context.
    Calls Gemini to compose an EventNarrative (typed structured output) and
    persists it onto the events document.

    Returns the narrative as a dict with keys:
        narrative_angle, key_figures, commercial_timing, historical_baseline

    Raises PreconditionError if the event is not found (call ingest_event_batch first).

    Independent of find_similar_assets and score_assets_with_vision — order among
    those three is your call; pick what makes sense for the situation. The narrative
    is consumed by propose_review_queue (required precondition) and by
    draft_campaigns_for_queue (copy substrate)."""
```

The docstring names the downstream consumers explicitly. This is the agent's contract: what to pass, what to expect back, what failure looks like, when it fits in the trajectory.

---

## System prompt context

`prompts/v2/agent_system.md` is unchanged in this step. The prompt already names "build context for the event (narrative grounded in player facts...)" as Phase 1, and the "order among independent prerequisites... is your call" sentence already covers the Step 2 / Step 3 / Step 4 emergent-order surface.

Confirmed: no prompt change required in Step 2. If trace eval diagnosis surfaces a prompt issue (per the remediation playbook), it lands then; do not pre-emptively edit.

---

## Risks

| Risk | Mitigation |
| --- | --- |
| LLM invents player facts not in `player_context.notable_facts` (hallucination) | Prompt is explicit ("verbatim subset"); response schema constrains `grounded_facts` to `list[str]`; eval asserts every `grounded_facts[i]` appears in the source player's `notable_facts`. If this fails, climb the remediation ladder per `evaluation-strategy.md` (prompt → docstring → schema constraint → hybrid validation in the wrapper). |
| LLM returns invalid JSON or malformed schema | `genai_types.GenerateContentConfig(response_mime_type="application/json", response_schema=EventNarrative)` forces structured output. `model_validate_json` raises on mismatch; capability lets it propagate (no silent recovery — fix the prompt). |
| Cohort empty (brand-new outcome_type — won't happen in seeded demo but could in production) | `HistoricalBaseline` has nullable `top_product_route` and explicit `notes` field for "no historical data yet". Prompt instructs the LLM to say so rather than fabricate. |
| Player context empty (team not in seed) | `key_figures` returns empty list (validates against `list[KeyFigure]`); prompt instructs the LLM to leave it empty rather than invent. |
| Performance aggregation returns inconsistent shape across MongoDB MCP versions | Wrapper parses the envelope shape (`{"content": [{"text": "..."}]}` per existing `client.py`); if structure shifts, we surface a clear error rather than coercing. |
| Two LLM calls per capability invocation (agent's planning + narrative generation) inflate latency | Both default to `gemini-2.5-flash-lite` (~1s each). If trace evals force a swap to `flash` for narrative composition, total per-event-context latency rises to ~3–6s; still within demo budget. |
| Trace eval's repeated narrative call is expensive (20× per eval run, multiplied by every CI) | Trace eval pass-rate gate runs locally on developer command, not on every push. CI runs unit tests + single-shot trace eval only. The 20× repeat is the ship-gate command, run before merge. |
| Mock-DB call-shape discrimination in `_MockMCPClient` becomes fragile as call surface grows | Extend `_MockMCPClient` with a small dispatch table keyed by `(tool_name, collection)`; tests register expected reads explicitly. Keeps the extension surgical rather than ad-hoc per-test. |
| `event_narrative` field on `Event` model creates a wide Event surface | Field is `EventNarrative | None` and both types live in `src/models.py` — no import cycle. Pydantic validates structure at insert/update. Trade-off: a malformed narrative now fails Event validation at write time, which is what we want — surface the bug at the persistence boundary, not at the consumer. |
| `GEMINI_NARRATIVE_MODEL` env var unset on production deploys | Defaults to `gemini-2.5-flash`; documented in `.env.example` and step-2 task list. |

**Hallucination is the primary risk in Step 2.** Vector search (Step 3) and Vision (Step 4) have wrapper-side ground truth; narrative composition does not, in the sense that fact-grounding lives only in the prompt + schema. The eval's "grounded_facts subset" assertion is the regression net.

---

## Env vars required

| Var | Purpose | Default |
| --- | --- | --- |
| `GOOGLE_API_KEY` | `google.genai` client (narrative LLM call) | None — required |
| `GEMINI_NARRATIVE_MODEL` | Model id for narrative composition | `gemini-2.5-flash-lite` |
| `GEMINI_MODEL` | Existing — agent's loop model | `gemini-2.5-flash-lite` |

`GOOGLE_API_KEY` is already in `.env.example` (used by `seed_mongodb.py`). New: `GEMINI_NARRATIVE_MODEL`. Update `.env.example` accordingly.

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v` | `EventNarrative`, `KeyFigure`, `HistoricalBaseline`, `Player` validate happy-path and reject malformed; `Event.event_narrative` accepts None and dict. |
| Wrappers (unit) | `.venv/bin/python -m pytest tests/test_step_2.py -v -k wrapper` | `get_event`, `find_past_events_by_outcome`, `update_event_narrative`, `aggregate_performance_for_events`, `find_players_for_teams` each call mocked client with correct `(database, collection, filter/pipeline)` shape and parse the envelope correctly. |
| Capability orchestration (unit) | `.venv/bin/python -m pytest tests/test_step_2.py -v -k capability` | `build_event_context` raises `PreconditionError` when event missing; calls 4 reads + LLM + 1 update in order; mocked `_run_narrative_llm` is invoked with a prompt that interpolates event/cohort/players/baseline; returns the narrative dict; persists `event_narrative` on events doc. |
| Cohort/player empty edge cases | `.venv/bin/python -m pytest tests/test_step_2.py -v -k empty` | When cohort empty: `HistoricalBaseline.past_event_count=0`, `top_product_route=None`; narrative still composed; prompt's "(no past events…)" branch fires. When player corpus empty: `key_figures=[]`; prompt's "(no seeded players…)" branch fires. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0/0.5/1/2 unit tests green. |
| **Trace eval — single run (outcome-shaped)** | `.venv/bin/python -m pytest tests/evals/test_step_2_trace.py -v` | Given a pre-seeded event in the mock DB (Argentina vs France, outcome_type=`upset_victory`, with player_context seeded for both teams + 3 past events of the same outcome_type) and operator prompt *"The event with id `evt-demo-1` has been ingested. Build context for it."*: (a) agent calls `build_event_context` exactly once with `event_id="evt-demo-1"`; (b) agent does **not** call `ingest_event_batch` (the event is already ingested per the operator prompt — calling ingest again would be a hallucinated tool); (c) mock client recorded reads on `events` (find by event_id), `events` (find by outcome_type), `performance` (aggregate), `player_context` (find by team); (d) mock client recorded one `update-many` on `events` setting `event_narrative` (filter is unique by event_id, so update-many semantics collapse to one-doc update — MongoDB MCP exposes `update-many` but not `update-one`); (e) the returned dict has the four `EventNarrative` top-level keys; (f) every `grounded_facts[i]` for every `key_figure` is a literal substring of that player's `notable_facts` (hallucination guard); (g) reasoning text is present before the tool call (CoT directive working); (h) on assertion failure, full trace dumped via `dump_trace()`. |
| **Trace eval — pass rate** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_2_trace.py -v` | ≥ 19/20 runs pass all eight assertions (95% threshold per D-020). |

Step 2's surface exercises **failure categories 1, 3, 4, 5** per `docs/plans/evaluation-strategy.md`: tool selection, tool arguments (correct `event_id`), tool-output handling (the hallucination guard is *category 4* — the model could correctly call the tool but the LLM-inside-tool could fabricate facts), end-state (narrative persisted with valid structure). Strategy coherence (category 6) does not apply until `propose_review_queue` ships.

Trace eval starts from a *pre-seeded* event in the mock DB rather than chaining ingestion. Rationale: isolates Step 2's behavior. Step 1's natural-language extraction is already covered by its own eval; combining them would muddy diagnosis. An end-to-end ingestion→context chain eval lands when more capabilities are in the surface and the chain itself is what we want to test.

---

## Output consumed by

- **`propose_review_queue` (capability 5)** — reads `event_narrative` from the events doc; refuses queue assembly if absent.
- **`draft_campaigns_for_queue` (capability 6)** — reads `event_narrative`; copy generation per D-016 uses `narrative_angle`, `key_figures[].grounded_facts`, and `commercial_timing` directly in headline/caption composition.
- **The trace** — judges watching the demo see a structured narrative emerge on screen (per `00-overview.md`'s demo narrative). This is the "MongoDB is load-bearing" moment for the `player_context` and `performance` collections specifically.

---

## What changed from prior planning docs

- **First "computational + LLM" capability** — Step 1 had no internal LLM call. The `_run_narrative_llm` helper pattern lands here and is reused in Step 4 (`score_assets_with_vision`) and Step 5 (`draft_campaigns_for_queue`).
- **`event_narrative` is persisted on the events doc** — not held only in agent state. This is a small departure from the surface reading of `02-architecture.md` § `build_event_context` ("returned to agent state, consumed by `draft_campaigns_for_queue`"). Persistence makes precondition enforcement on capability 5 cheap; agent-state-only would require the agent to pass the narrative as an argument to every downstream capability. Architecture-spec update will land with the Step 2 merge.
- **New `prompts/v2/build_event_context.md`** — capability-internal prompt, separate from the agent system prompt. Loader convention reused (`load_prompt("build_event_context")`).
- **New `GEMINI_NARRATIVE_MODEL` env var** — separates narrative model from agent-loop model. Default `gemini-2.5-flash`.

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

These are not optional follow-ups — implementation code in this branch must not contradict the spec it's written against. Two of them are doc-only changes that block code commits; one is a stale-line fix.

1. **New D-entry: persistence of `event_narrative` on the `events` document** (`tracking.md`).  
   D-016 + `02-architecture.md` § `build_event_context` currently say the narrative is *"returned to agent state, consumed by `draft_campaigns_for_queue`."* This plan adds persistence on the events doc so that `propose_review_queue` (capability 5) has a checkable precondition for the narrative existing — rather than requiring the agent to pass the multi-hundred-token payload through every downstream tool call. This is a real data-contract change. New D-entry captures the rationale and supersedes the relevant paragraph of D-016 (narrative is still consumed by `draft_campaigns_for_queue`; the in-state-only framing changes).

2. **`02-architecture.md` § `build_event_context` update.**  
   Reword the *"returned to agent state, consumed by `draft_campaigns_for_queue`"* paragraph to reflect persistence. Add `event_narrative` to the `events` collection JSON example. Add the `events.update-many` line to the MCP call list under `build_event_context`. Update the schema overview in `prompts/v2/agent_system.md` only if its current wording would be made wrong — currently it just says "Player biographical facts live in `player_context`" and similar, which stays correct.

3. **`tracking.md` § Planning Document Index stale-line fix.**  
   Step 1 is listed as *"Pending rewrite per D-021"* — Step 1 is complete and merged. Update to *"Complete — merged to `main`."*

Sequence on this branch:

1. Branch housekeeping commit (items 1–3 above) — doc-only, no code.
2. Plan + tasks gates (this document + the task list).
3. Implementation commits per task ordering.
4. Trace eval and pass-rate gate.
5. Merge to `main` with the updated "Next action" line in `CLAUDE.md`.

`_MockMCPClient` extension (read-shaped response dispatch) is part of Component 15 of the implementation, not housekeeping — listed here only to flag that it is a real extension and not a one-line tweak.
