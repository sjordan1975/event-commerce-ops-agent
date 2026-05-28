# Step 4 — Score Assets With Vision: Task List

> Tasks T-4.1 through T-4.14 implement the `score_assets_with_vision` capability per `docs/plans/step-4-vision.md`. One workflow `FunctionNode` (not a coordinator-facing tool — D-024) wrapping a per-asset Gemini Vision call (via `google.genai`, structured output) that produces a typed 5-dimensional `AssetScores` block + a `detected_subjects: list[str]` for each asset. One new internal Python wrapper in `src/db/assets.py`, one private Vision helper + one event-context-payload helper in the capability module, two new Pydantic models, one Asset retype + one new Asset field, one new prompt template. Tasks follow the plan's § Dependency order verbatim.

Prerequisites:
- Step 3 merged to `main` (find_similar_assets capability live; assets carry persisted embeddings + similar_assets).
- Branch `step/4-vision` is cut from current `main`.
- Branch housekeeping commit landed on `step/4-vision` (doc-only, no code) — see T-4.0.
- `MongoMCPClient` + `get_client()` lazy singleton unchanged. `PreconditionError` from `src/errors.py` reused (no new error type this step).
- D-024 workflow scaffolding from Steps 1/2/3 in place: `src/agent.py` `build_coordinator()` + `build_workflow()`, `src/capabilities/__init__.py` `build_pipeline_graph()` with chain `(START, ingest, context, similarity)`, `run_event_pipeline` coordinator shim, eval scaffolding's `_MockMCPClient` with collection-keyed dispatch and `$vectorSearch` discriminator.

Design decisions baked in (see `docs/plans/step-4-vision.md` for rationale):
- The capability is a `FunctionNode` in the workflow graph — **not** a coordinator-facing `FunctionTool`. The agent's tool surface remains `run_event_pipeline` (unchanged from Step 3).
- One new internal Python wrapper in `src/db/assets.py`: `save_asset_scores(asset_id, scores, detected_subjects)`. Bundled write — one `update-many` sets `scores`, `detected_subjects`, and `status: "scored"`.
- One private Vision helper `_score_asset_with_vision` in `src/capabilities/scoring.py` wraps `google.genai`'s `generate_content` for Gemini Vision with `response_schema=VisionScoringOutput`. Test seam for monkeypatching.
- One private context-payload helper `_build_event_context_payload(event_id)` reads the event + (optional) narrative for use in the per-asset prompt.
- Per-asset Vision call (no batching) — matches Step 3's per-asset loop; cardinality stays bounded (≤20 assets per event in the MVP).
- Idempotent skip: `if asset.scores is None`. Re-runs cheap; partial failures resume.
- Image-fetch logic is duplicated from `src/capabilities/similarity.py:_compute_image_embedding` — **do not extract a shared helper this step** (two instances is not enough surface).
- `Asset.scores` is retyped from `dict[str, Any] | None` to `AssetScores | None`. New `Asset.detected_subjects: list[str] | None` field.
- `GEMINI_VISION_MODEL` defaults to `gemini-2.5-flash` (not flash-lite — Vision is judgment-laden).
- Step 4 does **not** write `product_route` or `queue_type` — those belong to Step 5's `assign_asset_to_queue`.
- Trace eval starts from the same Argentina-vs-France operator prompt used in Steps 2 + 3, now with the seeded narrative + similarity fixture extended for scoring. Node firing is verified **indirectly** via the recorded call sequence on the mock client (Step 2/3 pattern).

---

## T-4.0: Branch housekeeping commit (doc-only, no code)

Files: `tracking.md`, `docs/specs/02-architecture.md`, `docs/specs/01-requirements.md`, `docs/db-wrapper-inventory.md`, `CLAUDE.md`
Acceptance — **all of the following land in a single doc-only commit before any code is written**:

1. **New D-entry**: `detected_subjects` extraction in Step 4 + identity composition in Step 5. Promotes the Messi-shots risk row from `docs/plans/step-3-similarity.md` to a formal decision. Captures: (a) Step 4 extracts `detected_subjects` as the structural fix for cosine's identity-blind behavior; (b) Step 5 composes `detected_subjects` against narrative `key_figures`; (c) field shape `list[str]` (not structured DetectedSubject); (d) hallucination guard lives in prompt + eval, not schema.
2. **New D-entry**: `Asset.scores` retyped to `AssetScores | None`. Rationale: typed boundary surfaces malformed score blocks at write time. Trade-off acknowledged: future score-dimension additions become a model change.
3. **New D-entry**: `GEMINI_VISION_MODEL` defaults to `gemini-2.5-flash`. Rationale: D-024's general workflow default is `flash-lite` for cost; Vision warrants the upgrade because of the `detected_subjects` hallucination surface + commercial-signal judgment density.
4. **`docs/specs/02-architecture.md` § `assets` schema**: add `detected_subjects: list[str] | null` to the JSON example; retype `scores` from inline dict shape to reference the `AssetScores` model. Update MCP call list under `score_assets_with_vision` to show the actual write (`assets update-many` setting scores + detected_subjects + status).
5. **`docs/specs/01-requirements.md` § `score_assets_with_vision`**: add the `detected_subjects` output to the capability description (one sentence).
6. **`docs/db-wrapper-inventory.md`**: `save_asset_scores` row updated to signature `save_asset_scores(asset_id, scores: AssetScores, detected_subjects: list[str]) -> None`; notes column captures the bundled-write rationale.
7. **`CLAUDE.md` § Current Phase**: update the "Next action" line to reflect that Step 4 plan + tasks are landed and implementation is beginning.

Verify: `git log -1 --stat` shows only doc files changed; no code under `src/` or `tests/` modified. `git diff main --stat` on this commit shows the seven files above.

---

## T-4.1: Add `AssetScores` Pydantic model

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `AssetScores(BaseModel)` with `model_config = ConfigDict(extra="forbid")`. Fields: `quality_score: float = Field(..., ge=0.0, le=1.0)`, `merch_score: float = Field(..., ge=0.0, le=1.0)`, `emotional_score: float = Field(..., ge=0.0, le=1.0)`, `social_score: float = Field(..., ge=0.0, le=1.0)`, `identity_score: float = Field(..., ge=0.0, le=1.0)`.
- Tests: happy-path construction; each dimension rejects values `< 0.0` and `> 1.0`; missing dimension raises; extra dimension (e.g. `timeliness_score=0.5`) raises (`extra="forbid"`).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k asset_scores`

---

## T-4.2: Add `VisionScoringOutput` Pydantic model

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `VisionScoringOutput(BaseModel)`. Fields: `scores: AssetScores`, `detected_subjects: list[str]`. **No** `extra="forbid"` — Gemini's `response_schema` rejects `additionalProperties:false` (verified empirically in Step 2; same constraint applies here).
- Tests: happy-path construction; `detected_subjects=[]` accepted (empty list is valid); nested `AssetScores` validation propagates (out-of-range score on `scores` raises at outer validation).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k vision_scoring_output`

---

## T-4.3: Retype `Asset.scores` and add `Asset.detected_subjects`

Files: `src/models.py` (modify `Asset`), `tests/test_models.py` (extend)
Acceptance:
- `Asset.scores: AssetScores | None = None` (was `dict[str, Any] | None`).
- `Asset.detected_subjects: list[str] | None = None` (new field, optional, defaults to `None`).
- Existing `Asset` tests continue to pass — both changes are additive at the optional/None boundary. Update any existing tests that construct `Asset(scores={"quality_score": ...})` to use `Asset(scores=AssetScores(...))` instead (audit with `grep -rn 'Asset(' tests/` and `grep -rn 'scores=' tests/`).
- New tests assert: (a) `Asset` constructs with `scores=None, detected_subjects=None`; (b) `Asset` constructs with `scores=AssetScores(...)` and `detected_subjects=["Lionel Messi"]`; (c) `Asset` rejects `scores={"quality_score": 0.9}` (dict no longer accepted under the typed boundary); (d) `Asset` rejects `detected_subjects=[123]` (Pydantic enforces `list[str]`).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k asset` and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green — catches any prior reader of `Asset.scores` that broke under the retype).

---

## T-4.4: Extend conftest helpers

Files: `tests/conftest.py`
Acceptance: Two new helpers:
- `build_valid_asset_scores(**overrides) -> AssetScores` — returns a valid `AssetScores` instance with sensible defaults (e.g. all dimensions set to 0.7).
- `build_valid_vision_scoring_output(**overrides) -> VisionScoringOutput` — returns a valid `VisionScoringOutput` with `scores=build_valid_asset_scores()`, `detected_subjects=["Lionel Messi"]` by default.

Both follow the `**overrides` pattern of the existing helpers (`build_valid_event`, `build_valid_asset`, `build_valid_similar_asset`).

Verify: `.venv/bin/python -c "from tests.conftest import build_valid_asset_scores, build_valid_vision_scoring_output; from src.models import AssetScores, VisionScoringOutput; s = build_valid_asset_scores(); assert isinstance(s, AssetScores) and 0.0 <= s.quality_score <= 1.0; v = build_valid_vision_scoring_output(); assert isinstance(v, VisionScoringOutput) and v.scores.quality_score == s.quality_score; print('ok')"`

---

## T-4.5: Implement `save_asset_scores` wrapper

Files: `src/db/assets.py` (extend), `tests/test_step_4.py` (new file)
Acceptance: `save_asset_scores(asset_id: str, scores: AssetScores, detected_subjects: list[str]) -> None` is async. Calls `get_client().call("update-many", {"database": "event_commerce", "collection": "assets", "filter": {"asset_id": asset_id}, "update": {"$set": {"scores": scores.model_dump(mode="json"), "detected_subjects": detected_subjects, "status": "scored"}}})`.

Unit test monkeypatches `src.db.assets.get_client`; asserts: (a) `update-many` invoked with the correct `(database, collection, filter, update)` shape; (b) `$set` contains all three keys (`scores`, `detected_subjects`, `status`); (c) `scores` is the serialized AssetScores dict (not the model instance); (d) `status` is exactly `"scored"`.

Verify: `.venv/bin/python -m pytest tests/test_step_4.py -v -k save_asset_scores`

---

## T-4.6: Add Vision prompt template

Files: `prompts/v3/score_asset_with_vision.md` (new)
Acceptance: New prompt file under the active `v3` prompt directory. Content matches the template in the plan's § "Vision prompt template" — sections: EVENT CONTEXT (with `(unavailable)` branch), SCORING DIMENSIONS split into Technical fitness (`quality_score`, `merch_score`) + Commercial signal (`emotional_score`, `social_score`, `identity_score`), DETECTED SUBJECTS section with the "only name when ... matches key_figures, bias toward empty over speculative" hallucination guard.

Loaded by the existing `src.prompt_loader.load_prompt("score_asset_with_vision")` — no loader changes needed (loader handles arbitrary names per Steps 2/3 precedent).

Verify: `.venv/bin/python -c "from src.prompt_loader import load_prompt; t = load_prompt('score_asset_with_vision'); assert 'SCORING DIMENSIONS' in t and 'DETECTED SUBJECTS' in t and 'key_figures' in t; print('ok')"`

---

## T-4.7: Implement `_score_asset_with_vision` helper

Files: `src/capabilities/scoring.py` (replace stub), `tests/test_step_4.py` (extend)
Acceptance: Private function `_score_asset_with_vision(image_url: str, event_context: dict) -> VisionScoringOutput` (sync — callers wrap in `asyncio.to_thread`, matching Step 2's `_run_narrative_llm` pattern):
- Reads `GOOGLE_API_KEY` env var (required) and `GEMINI_VISION_MODEL` env var (default `"gemini-2.5-flash"`).
- Fetches image bytes via duplicated logic from `src/capabilities/similarity.py:_compute_image_embedding` (HTTP/HTTPS via `urllib.request.urlopen`, otherwise local `open`). **Do not extract a shared helper.**
- Formats the prompt via `load_prompt("score_asset_with_vision").format(**event_context)`.
- Calls `genai.Client(api_key=...).models.generate_content(model=..., contents=[image_part, prompt], config=genai_types.GenerateContentConfig(response_mime_type="application/json", response_schema=VisionScoringOutput))` where `image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")`.
- Returns `VisionScoringOutput.model_validate_json(response.text)`.

Unit test patches `src.capabilities.scoring.genai.Client` (or equivalent boundary) to return a stub response whose `.text` is the serialized JSON of a `build_valid_vision_scoring_output()`. Asserts: (a) `generate_content` called with `response_schema=VisionScoringOutput` and `response_mime_type="application/json"`; (b) `contents` is a 2-element list `[image_part, prompt_string]`; (c) return value is a `VisionScoringOutput` with the stub's values; (d) when `response.text` is malformed JSON, `model_validate_json` raises (let it propagate — no silent recovery).

Verify: `.venv/bin/python -m pytest tests/test_step_4.py -v -k score_asset_with_vision_helper`

---

## T-4.8: Implement `_build_event_context_payload` helper

Files: `src/capabilities/scoring.py` (extend), `tests/test_step_4.py` (extend)
Acceptance: Async function `_build_event_context_payload(event_id: str) -> dict` returns a dict ready to splat into the prompt's format-string substitution. Keys: `outcome_type`, `final_score`, `narrative_angle`, `key_figure_names`.

Implementation:
- Call `await get_event(event_id)` (existing wrapper from `src/db/events.py`).
- If `event.event_narrative` is not None: use `narrative_angle=event.event_narrative.narrative_angle` and `key_figure_names=", ".join(kf.name for kf in event.event_narrative.key_figures)`.
- If `event.event_narrative` is None: use `narrative_angle="(unavailable)"` and `key_figure_names="(none)"`.
- Always use `outcome_type=event.outcome_type` and `final_score=event.final_score`.

Unit test monkeypatches `src.capabilities.scoring.get_event`; covers both branches (narrative present, narrative absent). Asserts the returned dict's keys and values match expectations in each branch.

Verify: `.venv/bin/python -m pytest tests/test_step_4.py -v -k build_event_context_payload`

---

## T-4.9: Implement `score_assets_with_vision` capability

Files: `src/capabilities/scoring.py` (replace stub body — keep the function name and module), `tests/test_step_4.py` (extend)
Acceptance: `score_assets_with_vision(event_id: str) -> dict` is async. Docstring matches the plan's § "Tool docstring" verbatim (load-bearing for capability legibility).

Body:
1. `assets = await get_assets_for_event(event_id)` (from `src/db/assets.py`, added in Step 3). Raise `PreconditionError(capability="score_assets_with_vision", context=event_id, missing={"assets": "no assets for event; call ingest_event_batch first"})` when empty.
2. `event_context = await _build_event_context_payload(event_id)`.
3. For each `asset` in `assets`:
   - If `asset.scores is not None`: skip (idempotent re-run guard).
   - Else: `output = await asyncio.to_thread(_score_asset_with_vision, asset.content_url, event_context)`; `await save_asset_scores(asset.asset_id, output.scores, output.detected_subjects)`; mutate `asset.scores = output.scores` and `asset.detected_subjects = output.detected_subjects` (keep local list in sync for the return shape).
4. Return:
   ```python
   {
       "event_id": event_id,
       "scored": [
           {
               "asset_id": a.asset_id,
               "scores": a.scores.model_dump(mode="json") if a.scores else None,
               "detected_subjects": a.detected_subjects or [],
           }
           for a in assets
       ],
   }
   ```

Unit tests (capability-level, mock both `get_client` and `_score_asset_with_vision`):
- `test_capability_raises_when_no_assets`: empty `get_assets_for_event` → `PreconditionError`.
- `test_capability_scores_each_unscored_asset`: 3 assets, none scored → `_score_asset_with_vision` called 3 times; `save_asset_scores` called 3 times; return has 3 entries with valid `scores` + `detected_subjects`.
- `test_capability_skips_already_scored_assets`: 3 assets, 1 already has `scores=AssetScores(...)` → helper called 2 times only; `save_asset_scores` called 2 times only; the pre-scored asset's existing values appear unchanged in the return.
- `test_capability_tolerates_missing_narrative`: event has `event_narrative=None` → capability still completes; `_score_asset_with_vision` is called with `event_context["narrative_angle"] == "(unavailable)"`.

Verify: `.venv/bin/python -m pytest tests/test_step_4.py -v -k capability`

---

## T-4.10: Wire workflow adapter + FunctionNode

Files: `src/capabilities/__init__.py` (modify)
Acceptance:
- Import: `from src.capabilities.scoring import score_assets_with_vision as _score_assets_with_vision`.
- New adapter `_node_score_assets_with_vision(ctx, event_id)`:
  ```python
  result = await _score_assets_with_vision(event_id)
  ctx.state["scored_assets"] = result["scored"]
  return result
  ```
- New module-level FunctionNode:
  ```python
  score_assets_with_vision_node = FunctionNode(
      func=_node_score_assets_with_vision,
      name="score_assets_with_vision",
      parameter_binding="state",
  )
  ```
- Update the module docstring's "Current pipeline" line to: `START → ingest_event_batch → build_event_context → find_similar_assets → score_assets_with_vision`. Remove the `Step 4 → adds score_assets_with_vision node` line from "Future steps extend the graph"; leave Steps 5/6 lines unchanged.

Unit test (in `tests/test_step_4.py`) asserts the adapter exists, has the right name on the FunctionNode, and writes `scored_assets` to `ctx.state` after calling the underlying capability (mock the capability).

Verify: `.venv/bin/python -m pytest tests/test_step_4.py -v -k node_adapter` and `.venv/bin/python -c "from src.capabilities import score_assets_with_vision_node; assert score_assets_with_vision_node.name == 'score_assets_with_vision'; print('ok')"`

---

## T-4.11: Extend `build_pipeline_graph` edge

Files: `src/capabilities/__init__.py` (modify)
Acceptance: `build_pipeline_graph()` returns:
```python
return [
    (START, ingest_event_batch_node, build_event_context_node, find_similar_assets_node, score_assets_with_vision_node),
]
```
Single chain-tuple extended from 4 → 5 elements. Docstring updated to reflect the new pipeline shape.

Verify: `.venv/bin/python -c "from src.agent import build_workflow; build_workflow(); print('ok')"` and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green — confirms the graph builds and no unit test regressed under the chain extension).

---

## T-4.12: Extend trace eval scaffolding

Files: `tests/evals/conftest.py` (modify)
Acceptance: Two scaffolding extensions:

1. **Vision-helper patch surface.** Add a `patch_vision_helper(client_calls_recorder, fixture_provider)` context manager (or extend an existing patching helper) that monkeypatches `src.capabilities.scoring._score_asset_with_vision` to return a deterministic `VisionScoringOutput`. The fixture provider receives `(image_url, event_context)` and returns a `VisionScoringOutput` — default implementation returns `build_valid_vision_scoring_output()` with `detected_subjects` populated from `event_context["key_figure_names"]` (so the hallucination-guard assertion in T-4.13 passes by construction; intentional regressions can override).

2. **Mock dispatch table extension for scoring writes.** `save_asset_scores` issues `update-many` on the `assets` collection — already covered by `_MockMCPClient`'s default "ok" handler for writes with no registered handler. No new dispatch entry required; document this in a comment in the conftest so future readers don't add a redundant handler. *(If `save_asset_scores` ever needs a return-shape mock, register it then — not now.)*

Verify: `.venv/bin/python -m pytest tests/evals/test_mock_dispatch.py -v` (existing mock-dispatch tests still green) plus a new mock-dispatch test asserting the Vision patch surface returns the expected stub.

---

## T-4.13: Trace eval — single run

Files: `tests/evals/test_step_4_trace.py` (new)
Acceptance: Single-run trace eval. Setup:
- Seeded event in mock DB: Argentina vs France, `outcome_type="upset_victory"`, with seeded `event_narrative` (`key_figures=[KeyFigure(name="Lionel Messi", ...), KeyFigure(name="Kylian Mbappé", ...)]`).
- 3 image fixtures registered as assets on the event, all without `scores` / `embedding` (will be embedded + scored in the workflow run).
- Seeded similarity fixture (Step 3 patch surface) returns deterministic neighbors so the similarity node completes.
- Vision-helper patch returns `VisionScoringOutput` whose `detected_subjects` is a subset of `["Lionel Messi", "Kylian Mbappé"]` (intentionally constructed to pass the substring guard).
- Operator prompt: same Argentina-vs-France batch submission used in Steps 2/3 evals.

Assertions:
- (a) Coordinator dispatches `run_event_pipeline` exactly once.
- (b) Mock client's recorded call sequence shows: ingest writes → context reads → context update → similarity reads/writes → scoring writes. (Node firing verified indirectly via call order, per Steps 2/3 idiom.)
- (c) Exactly 3× `update-many` calls on `assets` whose `$set` contains keys `scores`, `detected_subjects`, `status` (the scoring writes).
- (d) Returned `scored_assets` in session state has 3 entries; each has valid `AssetScores` (all 5 dims in [0, 1]) and `detected_subjects: list[str]`.
- (e) **Hallucination guard**: every entry in every asset's `detected_subjects` is a substring of `"Lionel Messi"` or `"Kylian Mbappé"` (the seeded key_figure names).
- (f) **Distributional sanity**: at least one asset has at least one score > 0.5 across the 3 assets (catches all-zero regression).
- (g) Reasoning text is present in the coordinator's pre-dispatch turn (CoT directive working).
- (h) On any assertion failure, full trace dumped via `dump_trace()`.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_4_trace.py -v`

---

## T-4.14: Trace eval — pass-rate gate

Files: none (uses T-4.13's test, run with `EVAL_REPEAT=20`)
Acceptance: 20-run pass rate ≥ 95% (≥ 19/20 runs pass all T-4.13 assertions). Per D-020, this is the ship gate for Step 4.

If the gate fails, climb the remediation ladder per `docs/evaluation-strategy.md` and `docs/feedback_evals_remediation_ladder.md`:
1. Prompt language (the Vision prompt template — sharpen rubrics or hallucination guard).
2. Capability docstring (rarely applies for non-agent-facing capabilities, but the coordinator system prompt may need tightening on dispatch).
3. Capability surface (the workflow node's contract).
4. Hybrid wrapper (e.g. wrapper-side `detected_subjects` filtering to drop non-key-figure names).
5. Model swap (`GEMINI_VISION_MODEL` env var — `flash-lite` → `flash` is already the default; `flash` → `pro` is the next rung).

Do **not** declare "acceptable for MVP" before trying the cheap rungs. Per the memory `feedback_evals_remediation_ladder`, this is a project-wide standard.

Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_4_trace.py -v`

---

## Verification checkpoints (rollup — must all pass before merge)

| After | Command | Must pass |
| --- | --- | --- |
| T-4.1 / T-4.2 / T-4.3 | `.venv/bin/python -m pytest tests/test_models.py -v` | `AssetScores`, `VisionScoringOutput`, `Asset.scores` retype, `Asset.detected_subjects` all validate per their tasks. |
| T-4.5 (wrapper) | `.venv/bin/python -m pytest tests/test_step_4.py -v -k wrapper` | `save_asset_scores` calls mocked client with correct shape. |
| T-4.7 / T-4.8 (helpers) | `.venv/bin/python -m pytest tests/test_step_4.py -v -k 'vision_helper or build_event_context_payload'` | Helpers invoke their dependencies correctly. |
| T-4.9 (capability) | `.venv/bin/python -m pytest tests/test_step_4.py -v -k capability` | Capability orchestrates correctly; raises `PreconditionError` on empty assets; skips already-scored; tolerates missing narrative. |
| T-4.10 / T-4.11 (graph wiring) | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Coordinator + workflow build cleanly with the extended graph. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0/1/2/3/4 unit tests green; no prior step regressed by the `Asset.scores` retype. |
| T-4.13 (trace eval single run) | `.venv/bin/python -m pytest tests/evals/test_step_4_trace.py -v` | All assertions pass single-run. |
| **T-4.14 (pass-rate gate — ship gate per D-020)** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_4_trace.py -v` | ≥ 19/20 runs pass. |

---

## Notes on task granularity

- T-4.1 and T-4.2 are split (not bundled) because `AssetScores` is reused outside `VisionScoringOutput` (it appears as a field on `Asset` directly per T-4.3). Splitting keeps the failure mode localized when one validation breaks.
- T-4.3 is a single task because the `Asset` retype + new field are inseparable from a downstream-reader perspective — both land before any code reads them.
- T-4.10 and T-4.11 are split because the adapter / FunctionNode is independently testable, while the graph-edge change is a single-line modification that only the integration check (`build_workflow()` smoke + full unit suite) exercises.
- T-4.13 and T-4.14 are split because the single-run trace eval is a different artifact than the pass-rate gate (different command, different failure-diagnosis path, different remediation cost).
- No task creates a separate `setup_*.py` script (unlike Step 3's vector index provisioning) — Step 4 has no out-of-band infrastructure step.

---

## What is intentionally not in this step

- **No identity-aware reranking in similarity.** That belongs to Step 5's `propose_review_queue` (composes `detected_subjects` against narrative `key_figures`). Step 4 only *extracts* the signal.
- **No `product_route` write.** Step 5's `assign_asset_to_queue` owns that boundary.
- **No `queue_type` write.** Same — Step 5 owns it.
- **No shared image-fetch helper.** Two instances is not enough surface; refactor only on the third caller.
- **No batched Vision call.** Per-asset matches Step 3's cardinality discipline; revisit only if the demo budget is exceeded.
- **No concurrent `asyncio.gather` over assets.** Sequential keeps the trace clean and avoids rate-limit complexity; revisit only on measured budget overrun.
