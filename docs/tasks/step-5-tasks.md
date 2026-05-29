# Step 5 — Propose Review Queue: Task List

> Tasks T-5.1 through T-5.14 implement the `propose_review_queue` capability per `docs/plans/step-5-queue.md` — **the one strategic decision** (D-021). Realized as three workflow nodes: a mechanical `prepare_queue_candidates` (`FunctionNode`), the project's **first in-graph `LlmAgent(mode='single_turn')` node** (`propose_review_queue`), and a defensive `persist_review_queue` (`FunctionNode`). Path A (the agent node) confirmed by `spike/adk_llm_node_queue_spike.py` (PASS mocked + live; 20/20 live pass-rate probe). Two new Pydantic models, two new `Asset` fields, one new DB wrapper, one new prompt, one new env var (`GEMINI_QUEUE_MODEL`). Tasks follow the plan's § Dependency order.

Prerequisites:
- Step 4 merged to `main` (`score_assets_with_vision` live; assets carry `scores: AssetScores` + `detected_subjects`).
- Branch `step/5-queue` cut from `main`.
- Branch housekeeping commit landed (T-5.0 — **done**, commit `f49e0be`).
- D-024 workflow scaffolding in place: `build_coordinator()` + `build_workflow()`, `build_pipeline_graph()` chain `(START, ingest, context, similarity, scoring)`, `run_event_pipeline` shim.
- Eval scaffolding from Steps 1–4: `_MockMCPClient` collection-keyed dispatch, the narrative/similarity/Vision patch surfaces (`_run_narrative_llm`, `_compute_image_embedding` + `vector_search_assets`, `_score_asset_with_vision`).
- `PreconditionError` from `src/errors.py` reused (no new error type).

Design decisions baked in (rationale in `docs/plans/step-5-queue.md` + D-029):
- **Agent node, not a `FunctionNode`+`genai` call.** `propose_review_queue` is an `LlmAgent(mode='single_turn')` with `output_schema=ReviewQueue` + `output_key="review_queue"`, instruction = a **callable provider** reading `ctx.state` (ADK uses the returned string verbatim — no re-templating, JSON-safe). The flanking `FunctionNode`s do all I/O.
- **`GEMINI_QUEUE_MODEL` defaults to `gemini-2.5-flash`** (not flash-lite — most judgment-dense node; D-028 precedent).
- **Mechanical cutoff split → LLM ordering/selection.** `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` (default `0.75`, corpus-tuned). Exploitation = top-neighbor similarity ≥ cutoff (carry `inferred_route`); discovery = the rest.
- **Exploitation routing stays mechanical** (`inferred_route`, D-015); discovery routing is the LLM's choice (the one place with no similarity signal).
- **Persist `queue_type`, `product_route`, `queue_rank`, `queue_rationale`** onto the asset (D-022). **No status change** (stays `"scored"` — Step 6 sets `"campaign_draft_created"`). Persisted enum is `"discovery"` (not "exploration").
- **All precondition checks live in `prepare_queue_candidates`**, never the instruction provider (ADK's raising-provider semantics untested).
- **`persist_review_queue` is defensive** — cross-assigned/invented `asset_id`s recorded as `membership_violations`, not crashed on.
- **Two-tier eval.** Tier 1 (`test_step_5_trace.py`, deterministic via `_FIXTURE_RESPONSE`, zero live calls) is the offline CI ship gate. Tier 2 (`test_step_5_coherence.py`, strategic node live) is the D-020 95%/20-run judgment gate, run deliberately; transient API errors retried/excluded so 95% measures judgment, not API uptime.

---

## T-5.0: Branch housekeeping commit (doc-only) — DONE

Landed in commit `f49e0be` (doc-only). For the record, it contained:

1. **D-029** in `tracking.md` — `propose_review_queue` as in-graph `LlmAgent` node (spike-validated) + all six sub-decisions + reconciliations.
2. **`docs/specs/02-architecture.md`** — `assets` schema gains `queue_rank`/`queue_rationale`; `propose_review_queue` MCP call list rewritten to the three nodes (no status change); graph diagram shows prepare/propose/persist; strategic node model → `GEMINI_QUEUE_MODEL` (flash); model-env-var bullet updated.
3. **`docs/specs/01-requirements.md`** — rank/rationale persisted; 90/10 is emergent shape not enforced cap.
4. **`docs/db-wrapper-inventory.md`** — `assign_asset_to_queue` → `save_queue_assignment(asset_id, queue_type, product_route, rank, rationale)`.
5. **`docs/safety-measures.md`** — `max_output_tokens` for the strategic node lands as a Step 5 task.

Verify (already satisfied): `git show f49e0be --stat` shows only doc files; no `src/` or `tests/` changes.

---

## T-5.1: Add `QueueItem` and `ReviewQueue` Pydantic models

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `QueueItem(BaseModel)` — **no** `extra="forbid"` (Gemini `response_schema` rejects `additionalProperties:false`, per Steps 2/4). Fields: `asset_id: str`, `queue_type: Literal["exploitation", "discovery"]`, `rank: int`, `product_route: Literal["poster", "tshirt", "social_only"] | None`, `rationale: str`.
- `ReviewQueue(BaseModel)` — no `extra="forbid"`. Fields: `event_id: str`, `exploitation: list[QueueItem]`, `discovery: list[QueueItem]`, `strategy_summary: str`.
- Tests: happy-path construction; `queue_type` rejects a value outside the two literals; `product_route` rejects an invalid route but accepts `None`; empty `exploitation`/`discovery` lists are valid; round-trips through `model_validate_json` (the `output_key` path lands a dict — assert `model_validate` on a dict works too).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k "queue_item or review_queue"`

---

## T-5.2: Add `Asset.queue_rank` and `Asset.queue_rationale`

Files: `src/models.py` (modify `Asset`), `tests/test_models.py` (extend)
Acceptance:
- `Asset.queue_rank: int | None = None` (new). `Asset.queue_rationale: str | None = None` (new). `queue_type` and `product_route` already exist — unchanged.
- Both additive at the optional/None boundary; existing `Asset` tests pass.
- New tests: `Asset` constructs with both `None` (default) and with `queue_rank=1, queue_rationale="..."`; rejects `queue_rank="first"` (Pydantic enforces `int`).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k asset` and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green).

---

## T-5.3: Extend conftest helpers

Files: `tests/conftest.py`
Acceptance: Two helpers following the `**overrides` pattern:
- `build_valid_queue_item(**overrides) -> QueueItem` — defaults: `asset_id="a1"`, `queue_type="exploitation"`, `rank=1`, `product_route="poster"`, `rationale="features the event's key figure"`.
- `build_valid_review_queue(**overrides) -> ReviewQueue` — defaults: `event_id="evt-demo-1"`, `exploitation=[build_valid_queue_item()]`, `discovery=[build_valid_queue_item(asset_id="a3", queue_type="discovery", product_route="social_only", rationale="no match but worth surfacing")]`, `strategy_summary="rich exploitation, one pointed discovery"`.

Verify: `.venv/bin/python -c "from tests.conftest import build_valid_review_queue; from src.models import ReviewQueue; q=build_valid_review_queue(); assert isinstance(q, ReviewQueue) and q.exploitation[0].queue_type=='exploitation' and q.discovery[0].queue_type=='discovery'; print('ok')"`

---

## T-5.4: Implement `save_queue_assignment` wrapper

Files: `src/db/assets.py` (extend), `tests/test_step_5.py` (new file)
Acceptance: `save_queue_assignment(asset_id: str, queue_type: str, product_route: str | None, rank: int, rationale: str) -> None` is async. Calls `get_client().call("update-many", {"database": "event_commerce", "collection": "assets", "filter": {"asset_id": asset_id}, "update": {"$set": {"queue_type": queue_type, "product_route": product_route, "queue_rank": rank, "queue_rationale": rationale}}})`.

Unit test monkeypatches `src.db.assets.get_client`; asserts: (a) `update-many` invoked with correct `(database, collection, filter)`; (b) `$set` contains exactly `queue_type`, `product_route`, `queue_rank`, `queue_rationale`; (c) **no `status` key** in `$set` (queue assignment does not transition status).

Verify: `.venv/bin/python -m pytest tests/test_step_5.py -v -k save_queue_assignment`

---

## T-5.5: Implement `prepare_queue_candidates` (preconditions + join + cutoff split)

Files: `src/capabilities/queue.py` (replace stub), `tests/test_step_5.py` (extend)
Acceptance: `prepare_queue_candidates(similarity_results: list[dict], scored_assets: list[dict], event_narrative: dict | None, cutoff: float) -> dict` — pure (no I/O, no ADK ctx):
- Raises `PreconditionError(capability="propose_review_queue", context=<event_id or "event">, missing={...})` if `similarity_results` is falsy ("call find_similar_assets first"), `scored_assets` is falsy ("call score_assets_with_vision first"), or `event_narrative` is None ("call build_event_context first"). All missing keys reported in one error.
- Joins `similarity_results` and `scored_assets` by `asset_id`. Per asset: `top_similarity = max((n["similarity"] for n in neighbors), default=0.0)`; `inferred_route` from the similarity result.
- Split: `top_similarity >= cutoff` → exploitation candidate (payload includes `asset_id`, `top_similarity`, `inferred_route`, `scores`, `detected_subjects`); else → discovery candidate (same payload, `inferred_route` carried but unused downstream).
- Returns `{"exploitation": [...], "discovery": [...]}`.
- `cutoff` defaults are read by the *adapter* from `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` (default `0.75`) — the pure function takes `cutoff` as a parameter for testability.

Unit tests: cutoff boundary (`top_similarity == cutoff` → exploitation; just below → discovery); empty `neighbors` → discovery (`top_similarity=0.0`); join correctness (scores + detected_subjects attached to the right asset); `inferred_route` carried into exploitation candidates; each precondition raises with the right `missing` keys; all-missing reports all three.

Verify: `.venv/bin/python -m pytest tests/test_step_5.py -v -k prepare`

---

## T-5.6: Add the strategist prompt template

Files: `prompts/v3/propose_review_queue.md` (new)
Acceptance: New prompt under `v3`. Content matches the plan's § "Strategist prompt template" — sections: EVENT (event_id, narrative angle, key figures); EXPLOITATION CANDIDATES (`{exploitation_json}`); DISCOVERY POOL (`{discovery_json}`); ASSEMBLE THE QUEUE with the four bullets (exploitation ordering + identity upweight + quality gate + carry route; discovery selection + "surface meaningful work" nudge + choose route; per-item rank + one-sentence rationale; strategy_summary). Format placeholders: `{event_id}`, `{narrative_angle}`, `{key_figures}`, `{exploitation_json}`, `{discovery_json}`.

Loaded via existing `load_prompt("propose_review_queue")` — no loader change.

Verify: `.venv/bin/python -c "from src.prompt_loader import load_prompt; t=load_prompt('propose_review_queue'); assert 'EXPLOITATION CANDIDATES' in t and 'DISCOVERY POOL' in t and 'surface meaningful work' in t.lower() and '{exploitation_json}' in t; print('ok')"`

---

## T-5.7: Implement `queue_instruction_provider`

Files: `src/capabilities/queue.py` (extend), `tests/test_step_5.py` (extend)
Acceptance: `queue_instruction_provider(ctx: ReadonlyContext) -> str`:
- Reads `ctx.state["event_narrative"]` and `ctx.state["queue_candidates"]` (assumes validated state — does **not** raise; preconditions are T-5.5's job).
- Builds `narrative_angle`, `key_figures` (comma-joined `key_figures` names), `exploitation_json` / `discovery_json` (`json.dumps(..., indent=2)`).
- Returns `load_prompt("propose_review_queue").format(event_id=..., narrative_angle=..., key_figures=..., exploitation_json=..., discovery_json=...)`.

Unit test with a fake `ReadonlyContext` (object exposing `.state`): asserts the returned string contains the narrative angle, key-figure names, and both candidate-pool asset_ids. (No raise path tested here — that's T-5.5.)

Verify: `.venv/bin/python -m pytest tests/test_step_5.py -v -k provider`

---

## T-5.8: Implement `build_review_queue_node` + eval-mock seam

Files: `src/capabilities/queue.py` (extend), `tests/test_step_5.py` (extend)
Acceptance:
- Module-level `_FIXTURE_RESPONSE: dict | None = None` (eval seam; set by Tier-1 conftest).
- `_queue_model_callback(callback_context, llm_request) -> LlmResponse | None`: returns `None` when `_FIXTURE_RESPONSE is None` (proceed to live model); else returns `LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(_FIXTURE_RESPONSE))]))`. **Reads the module global at call time** (import-order-safe).
- `build_review_queue_node() -> LlmAgent`: `model=os.environ.get("GEMINI_QUEUE_MODEL", "gemini-2.5-flash")`, `name="propose_review_queue"`, `mode="single_turn"`, `instruction=queue_instruction_provider`, `output_schema=ReviewQueue`, `output_key="review_queue"`, `before_model_callback=_queue_model_callback`, `generate_content_config=genai_types.GenerateContentConfig(max_output_tokens=<bounded>)` (the spend bound per `safety-measures.md` Gap 2 — size for the per-item-reasoning payload, e.g. 2048).

Unit tests: `build_review_queue_node()` returns an `LlmAgent` with `name=="propose_review_queue"`, `mode=="single_turn"`, `output_key=="review_queue"`; with `_FIXTURE_RESPONSE=None` the callback returns `None`; with `_FIXTURE_RESPONSE` set the callback returns an `LlmResponse` whose text parses into `ReviewQueue`.

Verify: `.venv/bin/python -m pytest tests/test_step_5.py -v -k "node_build or callback"`

---

## T-5.9: Implement `persist_review_queue` (defensive)

Files: `src/capabilities/queue.py` (extend), `tests/test_step_5.py` (extend)
Acceptance: `persist_review_queue(ctx) -> dict` is async:
- `queue = ReviewQueue.model_validate(ctx.state["review_queue"])` (handles dict; tolerate str via `model_validate_json`).
- Build `routes = {c["asset_id"]: c["inferred_route"] for c in ctx.state["queue_candidates"]["exploitation"]}` and `discovery_ids = {c["asset_id"] for c in ...["discovery"]}`.
- For each exploitation item: if `asset_id not in routes` → append to `violations` and skip; else `await save_queue_assignment(asset_id, "exploitation", routes[asset_id], item.rank, item.rationale)` (**mechanical route**, D-015).
- For each discovery item: if `asset_id not in discovery_ids` → `violations` + skip; else `await save_queue_assignment(asset_id, "discovery", item.product_route, item.rank, item.rationale)` (**LLM route**).
- Returns `{"review_queue": queue.model_dump(mode="json"), "membership_violations": violations}`.

Unit tests (mock `save_queue_assignment`, fake `ctx` with seeded `review_queue` + `queue_candidates`): exploitation items persisted with the mechanical `inferred_route` (not the LLM's `product_route`); discovery items persisted with the LLM route; un-surfaced discovery-pool assets get **no** `save_queue_assignment` call; a cross-assigned item (discovery asset placed in `exploitation`) is recorded in `membership_violations` and does **not** raise.

Verify: `.venv/bin/python -m pytest tests/test_step_5.py -v -k persist`

---

## T-5.10: Wire adapters + nodes + graph edges

Files: `src/capabilities/__init__.py` (modify), `tests/test_step_5.py` (extend)
Acceptance:
- Imports from `src.capabilities.queue`: `prepare_queue_candidates`, `build_review_queue_node`, `persist_review_queue`.
- Adapter `_node_prepare_queue_candidates(ctx)`: reads `ctx.state["similarity_results"]`, `ctx.state["scored_assets"]`, `ctx.state.get("event_narrative")`; `cutoff = float(os.environ.get("QUEUE_EXPLOITATION_SIMILARITY_CUTOFF", "0.75"))`; `candidates = prepare_queue_candidates(...)`; `ctx.state["queue_candidates"] = candidates`; return candidates.
- `prepare_queue_candidates_node = FunctionNode(func=_node_prepare_queue_candidates, name="prepare_queue_candidates", parameter_binding="state")`.
- `propose_review_queue_node = build_review_queue_node()` (module-level; the `LlmAgent` node — placed directly in the chain, validated by the spike).
- Adapter `_node_persist_review_queue(ctx)`: `result = await persist_review_queue(ctx)`; `ctx.state["review_queue"] = result["review_queue"]`; return result. `persist_review_queue_node = FunctionNode(..., name="persist_review_queue", parameter_binding="state")`.
- Update the module docstring "Current pipeline" line to include the three new nodes; drop the "Step 5 → adds propose_review_queue" future line.

Unit tests: adapters exist and write the right state keys (mock the underlying queue functions); `prepare_queue_candidates_node.name == "prepare_queue_candidates"`, `persist_review_queue_node.name == "persist_review_queue"`, `propose_review_queue_node.name == "propose_review_queue"`.

Verify: `.venv/bin/python -m pytest tests/test_step_5.py -v -k node_adapter` and `.venv/bin/python -c "from src.capabilities import prepare_queue_candidates_node, propose_review_queue_node, persist_review_queue_node; print('ok')"`

---

## T-5.11: Extend `build_pipeline_graph` + `run_event_pipeline` return + coordinator prompt

Files: `src/capabilities/__init__.py` (modify), `src/agent.py` (modify), `prompts/v3/coordinator_system.md` (light edit)
Acceptance:
- `build_pipeline_graph()` returns a single chain-tuple extended to 8 elements: `(START, ingest_event_batch_node, build_event_context_node, find_similar_assets_node, score_assets_with_vision_node, prepare_queue_candidates_node, propose_review_queue_node, persist_review_queue_node)`. Docstring updated.
- `run_event_pipeline` adds `"review_queue": state.get("review_queue")` to its returned dict.
- `prompts/v3/coordinator_system.md`: one-line addition — after `run_event_pipeline` returns, present the proposed review queue (both halves, with each item's rank, route, and rationale) to the operator. (No other coordinator change.)

Verify: `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green — graph builds with the `LlmAgent` node in the chain; no regressions).

---

## T-5.12: Extend trace-eval scaffolding (upstream-seeding + `_FIXTURE_RESPONSE` control + transient-error helper)

Files: `tests/evals/conftest.py` (modify)
Acceptance: Extend Step 4's scaffolding so a full `run_event_pipeline` dispatch flows through into the queue nodes with the upstream LLM calls patched (so only the strategic node can be live):
1. **Candidate-shaping fixtures.** Ensure the patched similarity surface (`vector_search_assets`) and Vision surface (`_score_asset_with_vision`) emit the spike's deliberately-unambiguous shape for the seeded event: ≥1 asset with strong similarity + a key-figure `detected_subject` (exploitation identity match), ≥1 asset with weak similarity + high `emotional_score` (worth-it discovery), ≥1 asset with weak similarity + low scores (not worth surfacing). Embedding + narrative patched as in Steps 2/3.
2. **`_FIXTURE_RESPONSE` control.** A fixture/context-manager that sets/clears `src.capabilities.queue._FIXTURE_RESPONSE` (Tier 1 sets a canned `ReviewQueue` dict matching the seeded pools; Tier 2 leaves it `None`).
3. **Transient-API-error helper (Tier 2).** A small retry/exclude wrapper: a run that fails with a transient API error (5xx / rate-limit / timeout from the live strategic-node call) is retried once, then excluded from the pass-rate denominator if still failing for infra reasons — so the 95% measures judgment, not API uptime. Judgment-assertion failures are **not** excluded.

Verify: `.venv/bin/python -m pytest tests/evals/test_mock_dispatch.py -v` (existing green) + a new mock-dispatch test asserting the `_FIXTURE_RESPONSE` control round-trips and the candidate-shaping fixtures produce the expected pools after `prepare`.

---

## T-5.13: Tier 1 — plumbing eval (deterministic, mocked, CI ship gate)

Files: `tests/evals/test_step_5_trace.py` (new)
Acceptance: Full `run_event_pipeline` dispatch with **`_FIXTURE_RESPONSE` set** (zero live calls), upstream patched per T-5.12. Same Argentina-vs-France operator prompt as Steps 2–4. Single run is authoritative (deterministic). Assertions:
- (T1-a) `ReviewQueue` parses from `review_queue` in the returned state (the canned dict round-trips through ADK `output_key`).
- (T1-b) `prepare_queue_candidates` split correct against the cutoff — exploitation vs. discovery membership matches the seeded similarities; `inferred_route` carried.
- (T1-c) `persist_review_queue` issued a `save_queue_assignment` (`update-many` on `assets` with `$set` = {queue_type, product_route, queue_rank, queue_rationale}, **no status**) per surfaced item; exploitation route == mechanical `inferred_route`; discovery route == canned LLM route; un-surfaced discovery assets got no write.
- (T1-d) a deliberately cross-assigned canned fixture variant is recorded in `membership_violations` and does not crash the run.
- (T1-e) coordinator dispatched `run_event_pipeline` exactly once; reasoning text present pre-dispatch (CoT directive); on failure `dump_trace()`.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_5_trace.py -v` (runs offline, no `GOOGLE_API_KEY` needed).

---

## T-5.14: Tier 2 — strategy-coherence eval (live strategic node) + pass-rate gate

Files: `tests/evals/test_step_5_coherence.py` (new)
Acceptance: Full dispatch with **`_FIXTURE_RESPONSE` unset** (strategic node live; ~1 live call/run), upstream patched per T-5.12. Tolerant strategy-coherence assertions (failure category 6, D-021):
- (T2-a) every exploitation item's `asset_id` ∈ exploitation candidate set; every discovery item's ∈ discovery pool.
- (T2-b) exploitation non-empty (matched winners surfaced).
- (T2-c) discovery non-empty (worth-it candidate surfaced) — "surface meaningful work".
- (T2-d) identity-matched asset appears in exploitation, not dropped (D-026); soft check: ranked 1 or 2 (tuning-flagged).
- (T2-e) every surfaced item has non-empty `rationale`; `strategy_summary` non-empty.
- (T2-f) `queue_type` matches half; ranks positive and distinct within each half.
- On failure `dump_trace()`. Transient API errors retried/excluded per T-5.12 (not counted as judgment failures).

Pass-rate gate: `EVAL_REPEAT=20`, ≥ 19/20 (95%, D-020). Spike pass-rate probe already measured 20/20 against these assertions — Tier 2 should pass comfortably.

If the gate softens, climb the remediation ladder per `docs/evaluation-strategy.md` / `feedback_evals_remediation_ladder` — prompt language first (strengthen the "surface meaningful work" / identity-upweight rubric), then docstring, then surface, then a hybrid mechanical hint in `prepare` (e.g. identity-boost flag exposed to the LLM), then model swap. **Never** a heuristic shortcut that collapses the strategic decision (Hard Constraint #1). Run deliberately (pre-merge / local / nightly) — not on offline code-CI.

Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_5_coherence.py -v` (requires `GOOGLE_API_KEY`).

---

## Verification checkpoints (rollup — must all pass before merge)

| After | Command | Must pass |
| --- | --- | --- |
| T-5.1 / T-5.2 | `.venv/bin/python -m pytest tests/test_models.py -v` | `QueueItem`/`ReviewQueue` validate + reject bad enums; `Asset.queue_rank`/`queue_rationale` validate. |
| T-5.4 (wrapper) | `.venv/bin/python -m pytest tests/test_step_5.py -v -k save_queue_assignment` | `$set` has the four queue fields, no `status`. |
| T-5.5 (prepare) | `.venv/bin/python -m pytest tests/test_step_5.py -v -k prepare` | Cutoff split, join, `inferred_route` carry, all three preconditions raise. |
| T-5.7 / T-5.8 / T-5.9 | `.venv/bin/python -m pytest tests/test_step_5.py -v -k "provider or node_build or callback or persist"` | Provider builds prompt (no raise); node constructed correctly; callback seam works; persist mechanical/LLM routing + defensive violations. |
| T-5.10 / T-5.11 (wiring) | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Graph builds with the `LlmAgent` node in the 8-element chain. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–5 unit tests green; no regression. |
| **Tier 1 — plumbing gate (CI)** | `.venv/bin/python -m pytest tests/evals/test_step_5_trace.py -v` | Deterministic; (T1-a)–(T1-e); offline, no API key. The gate `main` stays green against. |
| **Tier 2 — coherence gate (D-020, deliberate)** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_5_coherence.py -v` | ≥ 19/20 on (T2-a)–(T2-f); transient API errors excluded. |

---

## Notes on task granularity

- T-5.1 / T-5.2 split: `QueueItem`/`ReviewQueue` (LLM output schema) are distinct from the `Asset` persisted-field additions; different failure modes.
- T-5.5 (prepare) is one task — preconditions + join + cutoff split are one cohesive pure function; splitting the precondition check from the split would fragment a single testable unit.
- T-5.8 bundles the node builder with the `_queue_model_callback`/`_FIXTURE_RESPONSE` seam because the seam only has meaning as a constructor argument of the node.
- T-5.10 / T-5.11 split: adapters + node instances are independently unit-testable; the graph-edge + `run_event_pipeline` + coordinator-prompt change is the integration layer exercised by the build-smoke + full suite.
- T-5.13 / T-5.14 split: the two eval tiers are different artifacts (deterministic vs. live), different commands, different CI posture (gate vs. deliberate), different remediation cost. This split *is* the two-tier decision (D-029).

---

## What is intentionally not in this step

- **No status transition on queue assignment.** Assets stay `"scored"`; Step 6 sets `"campaign_draft_created"`.
- **No enforced 90/10 budget.** The split is emergent (cutoff + agent selection); no cap (D-029).
- **No campaign drafting.** `draft_campaigns_for_queue` (Step 6) reads the persisted queue fields as substrate.
- **No HITL.** `request_human_approval` (Step 7) is coordinator-side; Step 5 only produces and surfaces the queue.
- **No live model in the CI gate.** Tier 1 is mocked; live judgment lives in Tier 2, run deliberately.
- **No heuristic fallback for queue assembly.** The strategic decision may not collapse to deterministic ranking (Hard Constraint #1).
