# Step 4 — `score_assets_with_vision`: Implementation Plan

## Context

Step 4 delivers the `score_assets_with_vision` capability — for every asset on the current event, it calls Gemini Vision to produce a structured 5-dimensional score block and a list of `detected_subjects`, persists both onto the asset document, and writes results to session state. This is the second "computational + LLM" capability (the pattern was set by Step 2's `build_event_context`) and the first capability whose LLM call has **per-asset cardinality** rather than per-event.

Per D-017's dual-job framing, the five dimensions split into two roles:

- **Technical fitness** (near-objective observable properties): `quality_score`, `merch_score`. The exploitation queue's quality gate — catches images that are compositionally similar to past winners but technically unfit for production.
- **Commercial signal** (interpretive assessment of observable qualities that correlate with commercial outcomes): `emotional_score`, `social_score`, `identity_score`. Ranking refinement within a channel + the per-queue routing-suggestion signal for discovery items.

`detected_subjects` is new in Step 4 (promoted from Step 3's risk-table flag, now formalized as a D-entry — see § Branch housekeeping). It is the structural fix for the **Messi-shots problem**: cosine on a multimodal embedding does not preserve subject identity as the dominant similarity signal. Step 5's `propose_review_queue` composes `detected_subjects` against the narrative's `key_figures` to upweight identity-matched neighbors over generic-scene matches. Without this extraction, the identity signal is lost between Steps 3 and 5.

Prerequisite: Step 3 (`find_similar_assets`) is merged to `main`. The workflow graph contains `START → ingest_event_batch → build_event_context → find_similar_assets`. Step 4 extends it with `score_assets_with_vision` as the fourth node.

---

## What this capability delivers

Workflow node `score_assets_with_vision` reads `event_id` from session state. It then:

1. Loads the event's assets via `get_assets_for_event(event_id)`.
2. For each asset *without* a scores block: calls `_score_asset_with_vision(content_url, event_context)` → Gemini Vision with `response_schema=VisionScoringOutput`, then persists via `save_asset_scores(asset_id, scores, detected_subjects)`. Idempotent — assets that already carry a `scores` block are skipped.
3. Returns `{"event_id": str, "scored": list[ScoredAsset]}` where each `ScoredAsset` is `{asset_id, scores: AssetScores, detected_subjects: list[str]}`.

Writes `scored_assets` to session state for downstream nodes.

Consumed by:
- **`propose_review_queue` (capability 5)** — hard precondition. Queue assembly needs scores (quality gate + ranking) and `detected_subjects` (identity composition with narrative key_figures). Refuses if absent.
- **`draft_campaigns_for_queue` (capability 6)** — reads the persisted `scores` for routing-recommendation ranking inside the draft prompt.

---

## The capability surface (D-019 + D-021)

| Surface | Type | Notes |
| --- | --- | --- |
| `score_assets_with_vision_node` | `FunctionNode` (workflow graph) | New node added to `build_pipeline_graph()`. Edge: `find_similar_assets → score_assets_with_vision`. Reads `event_id` from state; writes `scored_assets`. |
| `_node_score_assets_with_vision` | adapter (`src/capabilities/__init__.py`) | Wraps `score_assets_with_vision()` and writes outputs back to `ctx.state`. Same pattern as the existing three adapters. |
| `score_assets_with_vision` | capability function (`src/capabilities/scoring.py`) | Replaces the existing stub. Internal to the workflow node. |

Internal Python wrappers added this step (none agent-facing; none registered as `FunctionTool`s):

| Wrapper | File | Purpose |
| --- | --- | --- |
| `save_asset_scores(asset_id, scores, detected_subjects)` | `src/db/assets.py` (extension) | Persists the 5-dim score block + `detected_subjects` list. **Signature deviation from `db-wrapper-inventory.md`:** the inventory entry is `save_asset_scores(asset_id, scores: AssetScores) -> None`. This plan adds `detected_subjects: list[str]` as a second positional argument so both writes land in one `update-many` call. Inventory updated in branch housekeeping. |

Plus non-MongoDB (internal to the capability):

| Helper | File | Purpose |
| --- | --- | --- |
| `_score_asset_with_vision(image_url, event_context)` | `src/capabilities/scoring.py` (private function) | Wraps the `google.genai` SDK `generate_content` call for Gemini Vision with `response_mime_type="application/json"`, `response_schema=VisionScoringOutput`, and image bytes via `Part.from_bytes`. Returns a validated `VisionScoringOutput`. Testable via monkeypatch on `src.capabilities.scoring._score_asset_with_vision`. |

The image-fetch logic is duplicated from `src/capabilities/similarity.py:_compute_image_embedding`. **Do not extract a shared helper yet** — two instances is not enough surface to justify the abstraction, and Step 3 / Step 4 have distinct error semantics (embedding-dim mismatch vs. vision-schema mismatch) that would collide in a shared module. Revisit only if a third caller appears.

`get_assets_for_event` was added in Step 3 and is reused unchanged.

Per D-019, `MongoMCPClient` remains the only MongoDB programmatic client; the new wrapper calls `get_client().call(...)` exactly like prior wrappers.

---

## What the LLM does in this capability

Two distinct LLM invocations occur during a Step 4 dispatch:

1. **The coordinator's `run_event_pipeline` dispatch decision** (outside the workflow). Unchanged from Steps 1–3 — coordinator decides to invoke the workflow; the workflow then runs deterministically per the graph.

2. **The per-asset Vision call** (inside the capability, per asset, cardinality = number of unscored assets on the event). Direct `google.genai` SDK call with `response_schema=VisionScoringOutput`. The model is shown one image at a time plus a small event-context block (outcome_type, narrative_angle from `event_narrative`, key_figure names) so it can ground `detected_subjects` against the names the narrative is already tracking.

The Vision call is **bounded reasoning** (per `agentic-model.md`): the model produces a structured artifact from a fixed input. It is *not* a strategic decision — the strategic surface is Step 5.

### Internal-LLM-call pattern (reused from Step 2)

```python
async def _score_asset_with_vision(image_url: str, event_context: dict) -> VisionScoringOutput:
    """Single-call Gemini Vision with structured output. Internal."""
    api_key = os.environ["GOOGLE_API_KEY"]
    model = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash")
    image_bytes = _fetch_image_bytes(image_url)  # duplicated from similarity.py — see § above

    client = genai.Client(api_key=api_key)
    image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    prompt = load_prompt("score_asset_with_vision").format(**event_context)

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=[image_part, prompt],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VisionScoringOutput,
        ),
    )
    return VisionScoringOutput.model_validate_json(response.text)
```

Rationale:
- **`gemini-2.5-flash`, not flash-lite.** Vision scoring is judgment-laden (interpretive `emotional_score` / `social_score` / `identity_score`) and the named-subject extraction has a hallucination surface that benefits from the stronger model. `GEMINI_VISION_MODEL` env var allows downgrade for cost-tuning later; default lives on `flash`.
- **Schema-bound output.** `response_schema=VisionScoringOutput` makes parsing failures impossible at the deserialization level.
- **Direct `google.genai` over an ADK sub-runner.** Same rationale as Step 2 — no tools to call, ADK runner is overkill.
- **Testable boundary.** Unit tests monkeypatch `src.capabilities.scoring._score_asset_with_vision`; trace evals patch the same seam to avoid live API quota burn (per-asset × 20 reps × up to 20 assets = up to 400 Vision calls per gate run).

---

## What the capability does internally

```text
score_assets_with_vision(event_id: str) → dict
    1. assets = await get_assets_for_event(event_id)
         raises PreconditionError if event has no assets (call ingest_event_batch first)
    2. event_context = await _build_event_context_payload(event_id)
         reads events.event_narrative (may be None — capability tolerates this and
         passes a minimal context block; eval covers the path)
    3. for asset in assets:
           if asset.scores is None:
               output = await _score_asset_with_vision(asset.content_url, event_context)
               await save_asset_scores(asset.asset_id, output.scores, output.detected_subjects)
               asset.scores = output.scores
               asset.detected_subjects = output.detected_subjects
    4. return {
           "event_id": event_id,
           "scored": [{"asset_id": a.asset_id, "scores": a.scores.model_dump(),
                       "detected_subjects": a.detected_subjects} for a in assets],
       }
```

Step 1 (assets loaded) is the only hard precondition that raises. Step 2 tolerates a missing narrative — the capability is independent of `build_event_context` *by graph contract* (per D-021, the three middle capabilities have no order constraint among themselves; the graph happens to wire them sequentially in D-024 but the capability does not assume it). When the narrative is absent, `event_context` carries only `outcome_type` and `final_score` from the event document. The prompt has a branch for this case.

`event.event_narrative` *will* be populated under the normal D-024 graph order (`build_event_context` runs before `score_assets_with_vision`). The tolerance is defense-in-depth, not a normal-path concern, and matches the Step 3 idiom that the capability functions correctly when invoked directly (e.g. unit tests, future parallel-execution refactors).

---

## Pydantic models (new)

```python
class AssetScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_score: float = Field(..., ge=0.0, le=1.0)      # technical fitness
    merch_score: float = Field(..., ge=0.0, le=1.0)        # technical fitness
    emotional_score: float = Field(..., ge=0.0, le=1.0)    # commercial signal
    social_score: float = Field(..., ge=0.0, le=1.0)       # commercial signal
    identity_score: float = Field(..., ge=0.0, le=1.0)     # commercial signal


# Vision LLM response schema — extra="forbid" omitted: Gemini's response_schema rejects
# additionalProperties:false (verified empirically in Step 2).
class VisionScoringOutput(BaseModel):
    scores: AssetScores
    detected_subjects: list[str]   # named players / people visible in the frame; [] when none
```

Modification to existing `Asset`:

```python
class Asset(BaseModel):
    # ... existing fields ...
    scores: AssetScores | None = None              # was: dict[str, Any] | None — typed in this step
    detected_subjects: list[str] | None = None     # new — populated by score_assets_with_vision
```

Retyping `Asset.scores` from `dict[str, Any]` to `AssetScores | None` is a real data-contract change. Trade-off accepted: the typed boundary surfaces a malformed score block at validation time (where we want it) rather than at a consumer (Step 5 ranking) far from the write. Existing tests that read `asset.scores["quality_score"]` would break under attribute access — none currently exist (the stub never wrote scores). Branch housekeeping commit retypes the field; Step 5's planning inherits the typed contract.

`detected_subjects` is the new field carrying Step 5's identity-routing signal. List-of-strings shape, not a structured `DetectedSubject` model, because the only consumer (Step 5) needs name matching against `KeyFigure.name` — adding bounding boxes or confidence scores would be unused YAGNI surface.

---

## Persistence: `scores` and `detected_subjects` on `assets`

Both fields are written together in one `save_asset_scores` call. The wrapper performs:

```text
assets.update-many({asset_id: <id>}, {$set: {
    scores: <serialized AssetScores>,
    detected_subjects: <list[str]>,
    status: "scored",
}})
```

`status: "scored"` is the asset-lifecycle transition that Step 5's `assign_asset_to_queue` expects. Writing it here keeps the transition co-located with the data that justifies it — an asset is "scored" exactly when its score block lands.

Both fields are recomputable in principle (Vision is non-deterministic; re-running could produce slightly different scores). The capability still gates on `asset.scores is None` and skips re-scoring — re-runs are cheap, deterministic enough for the demo, and the trace stays clean.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `AssetScores`, `VisionScoringOutput` models | `src/models.py` (extension) | Typed 5-dim score block + Vision LLM response shape |
| 2 | `Asset.scores` retype + `Asset.detected_subjects` field | `src/models.py` (modification) | `scores: AssetScores \| None` (was `dict`), new `detected_subjects: list[str] \| None` |
| 3 | `save_asset_scores` wrapper | `src/db/assets.py` (extension) | Persists scores + detected_subjects + status transition in one update |
| 4 | `_score_asset_with_vision` helper | `src/capabilities/scoring.py` | Gemini Vision call with structured-output schema |
| 5 | `_build_event_context_payload` helper | `src/capabilities/scoring.py` | Reads event + event_narrative, returns minimal context dict for the prompt |
| 6 | `score_assets_with_vision` capability | `src/capabilities/scoring.py` (replaces stub) | Orchestrates load → score-and-persist loop |
| 7 | `_node_score_assets_with_vision` adapter | `src/capabilities/__init__.py` (modification) | Workflow adapter that writes `scored_assets` to state |
| 8 | `score_assets_with_vision_node` FunctionNode | `src/capabilities/__init__.py` (modification) | Module-level FunctionNode instance, `parameter_binding="state"` |
| 9 | `build_pipeline_graph` edge | `src/capabilities/__init__.py` (modification) | Extend the chain tuple from 4 → 5 elements: `(START, ingest, context, similarity, scoring)` |
| 10 | Vision prompt template | `prompts/v3/score_asset_with_vision.md` (new) | Capability-internal prompt; encodes D-017 dual-job framing + detected_subjects hallucination guard |
| 11 | Conftest helpers | `tests/conftest.py` (extension) | `build_valid_asset_scores()`, `build_valid_vision_scoring_output()` |
| 12 | Tests — unit | `tests/test_step_4.py` (new), `tests/test_models.py` (extension) | Models; wrapper (mocked MCP envelope); capability orchestration with mocked Vision helper; idempotent re-score skip; empty-assets PreconditionError; missing-narrative tolerance |
| 13 | Tests — trace eval | `tests/evals/test_step_4_trace.py` (new) | Outcome-shaped trace eval (single-run + N=20 repeat) — dispatches `run_event_pipeline` end-to-end with mocked Vision helper |
| 14 | Eval conftest extension | `tests/evals/conftest.py` (modification) | Vision-helper patch surface so traces don't hit live Gemini Vision; extend mock dispatch with seeded scoring fixtures |

---

## Dependency order

1. **Models** — `AssetScores`, `VisionScoringOutput`; retype `Asset.scores`; add `Asset.detected_subjects`
2. **Conftest helpers** — `build_valid_asset_scores()`, `build_valid_vision_scoring_output()`
3. **`save_asset_scores` wrapper** — unit-tested independently via monkeypatched client; asserts the `update-many` envelope shape sets all three fields (`scores`, `detected_subjects`, `status: "scored"`)
4. **Vision prompt** — `prompts/v3/score_asset_with_vision.md`; fixed text with format-string substitution
5. **`_score_asset_with_vision` helper** — unit-tested with a mocked `genai.Client`; verifies the prompt loads, the image-bytes path runs, the response schema validates
6. **`_build_event_context_payload` helper** — unit-tested with mocked `get_event`; verifies missing-narrative fallback
7. **`score_assets_with_vision` capability** — composes load + score-loop; unit test mocks both `get_client` (per-module) and `_score_asset_with_vision`; covers idempotent skip, empty-assets precondition, missing-narrative tolerance
8. **Workflow adapter + FunctionNode + graph edge** (`src/capabilities/__init__.py`) — `_node_score_assets_with_vision`, `score_assets_with_vision_node`, extend the chain tuple
9. **Trace eval scaffolding extension** (`tests/evals/conftest.py`) — Vision-helper patch surface
10. **Trace eval — single run** (`tests/evals/test_step_4_trace.py`) — outcome-shaped assertions per the verification table
11. **Trace eval — pass rate** — `EVAL_REPEAT=20`, ≥ 95% threshold per D-020

---

## Tool docstring (capability docstring — load-bearing for evals and capability legibility)

```python
async def score_assets_with_vision(event_id: str) -> dict:
    """Scores every asset on the event along five dimensions via Gemini Vision.

    For every asset on the event without an existing scores block, calls
    Gemini Vision once with the image bytes + a small event-context block.
    The model returns:
      - scores: AssetScores with five [0,1] dimensions (D-017 dual-job):
          quality_score, merch_score        — technical fitness
          emotional_score, social_score,
          identity_score                    — commercial signal
      - detected_subjects: list[str] of named players / people visible in the frame
        (empty when no recognizable subject is present)

    Persists both onto the asset document and transitions status to "scored".
    Idempotent — assets that already carry a scores block are skipped on re-run.

    Returns {"event_id": str, "scored": list[{asset_id, scores, detected_subjects}]}.

    Raises PreconditionError if the event has no assets (call ingest_event_batch
    first). Tolerates a missing event_narrative — uses minimal event context in
    that case, but D-024 graph order ensures the narrative is normally present.

    Consumed by propose_review_queue (required precondition — scores for quality
    gate + ranking; detected_subjects for identity composition with narrative
    key_figures) and draft_campaigns_for_queue (reads asset.scores for in-prompt
    routing-recommendation ranking)."""
```

---

## Vision prompt template (load-bearing — eval asserts on its output structure)

`prompts/v3/score_asset_with_vision.md` is a single template the capability formats with a small event-context block. Shape (Python-side substitution, not Jinja):

```text
You are scoring one sports event photograph for an editorial commerce workflow.
Output JSON matching the VisionScoringOutput schema. Score every dimension on
the [0.0, 1.0] interval; explicit zeros are valid.

EVENT CONTEXT
- outcome_type: {outcome_type}
- final_score: {final_score}
- narrative_angle: {narrative_angle}
- key_figures: {key_figure_names}

(If narrative_angle is "(unavailable)", score the image on its visual merits alone.)

SCORING DIMENSIONS

Technical fitness — observable properties of the image itself:
- quality_score: sharpness, exposure, resolution, printability.
  0.0 = motion-blurred / underexposed / unprintable. 1.0 = razor-sharp, print-grade.
- merch_score: subject silhouette clarity and framing for poster/t-shirt use.
  0.0 = cluttered, off-center, no clean silhouette. 1.0 = iconic framing.

Commercial signal — interpretive assessment of qualities that correlate with
commercial outcomes:
- emotional_score: peak human drama visible in the frame (celebration, despair,
  triumph, exhaustion).
  0.0 = neutral / static. 1.0 = visceral peak-moment emotion.
- social_score: scroll-stop probability at thumbnail scale (high contrast,
  recognizable shapes, color punch).
  0.0 = visually flat at thumbnail size. 1.0 = unmistakable at small size.
- identity_score: fan-belonging signal — visible team colors, recognizable jersey
  numbers, recognizable faces of named players from key_figures.
  0.0 = no identifiable team/player signal. 1.0 = unmistakable identity cue.

DETECTED SUBJECTS

List the named players / people who are recognizably visible in the frame.
- Only name a subject when their face or unambiguous jersey identifier is visible
  AND the name matches one in the key_figures list above. If uncertain, leave
  empty — do not guess. Generic descriptors ("a player", "the goalkeeper") are
  never valid entries. Crowd shots with no named figure return an empty list.
- This list is consumed downstream to compose identity-matched routing; a false
  positive here causes mis-routing. Bias toward empty over speculative.
```

The "only name a subject when ... matches one in the key_figures list" + "bias toward empty over speculative" framing is the hallucination guard for `detected_subjects`. Eval asserts every entry in `detected_subjects` is a substring of some key-figure name (or, when narrative is unavailable, asserts `detected_subjects == []`).

---

## System prompt context

`prompts/v3/coordinator_system.md` does **not** need to change for Step 4. The coordinator still dispatches `run_event_pipeline`; the workflow extends underneath it transparently. Confirmed: no prompt change required in Step 4.

---

## Risks

| Risk | Mitigation |
| --- | --- |
| Gemini Vision rate-limits during trace eval (20 reps × up to 20 assets per event = up to 400 Vision calls per gate run) | Eval patches `src.capabilities.scoring._score_asset_with_vision` to return deterministic `VisionScoringOutput` fixtures. Live API exercised only in a separate `tests/test_vision_smoke.py` (out-of-band). |
| Hallucinated `detected_subjects` — Vision invents player names not visible in the frame | Prompt: "Only name when face or unambiguous jersey identifier is visible AND name matches key_figures. Bias toward empty over speculative." Eval asserts every name is a key-figure-name substring. If this fails, climb the remediation ladder (prompt → docstring → schema constraint → hybrid wrapper-level validation that strips non-key-figure names). |
| Score block out of range (Vision returns 1.5 or -0.1) | `AssetScores` has `Field(..., ge=0.0, le=1.0)` per dim; `model_validate_json` raises on out-of-range. Capability lets it propagate. |
| Vision LLM returns invalid JSON / wrong schema | `response_schema=VisionScoringOutput` forces structured output. `model_validate_json` raises on mismatch; no silent recovery. |
| Image fetch fails (network, missing local file) | `_fetch_image_bytes` raises `IOError`/`URLError`; capability propagates. For the eval, the Vision-helper patch bypasses fetching entirely. Live demo asset URLs validated as reachable in a separate `scripts/verify_image_reachability.py` script (out-of-band). |
| Per-asset Vision call is slow (~2–4s on `flash`) → 20 assets per event = ~40–80s per dispatch | Within demo budget (target: under 60s for 50-image batch per success metrics; Step 4 is the dominant cost). Optimization deferred — concurrent calls via `asyncio.gather` are an option but introduce complexity; defer until the demo budget is exceeded in measured runs. |
| Idempotent skip silently masks a corrupted score block (e.g. all zeros from a Vision regression) | Wrapper writes a typed `AssetScores` — Pydantic enforces structure but not "meaningfulness." All-zero scores are not guarded for. The eval's per-dim distributional check (at least one score > 0.5 across 20-asset fixture batch) catches gross regressions. |
| Step 4 silently overwrites a hand-edited `scores` block on re-run | The `is None` skip protects this. If a future operator workflow involves manual score edits, the gate becomes wrong — but no such workflow exists in the MVP. Flagged for Step 5+ planning, not addressed here. |
| Vision model env var `GEMINI_VISION_MODEL` unset on prod deploys | Defaults to `gemini-2.5-flash`. Documented in the env section + README. |
| Narrative absent at score time (re-running Step 4 before Step 2 fires, or eval seeding a partial graph) | Capability tolerates `event_narrative=None` and passes `(unavailable)` to the prompt; the prompt has a branch that scores on visual merits alone and returns `detected_subjects=[]`. Unit test covers this branch. |
| `Asset.scores` retype from `dict[str, Any]` to `AssetScores \| None` breaks an existing reader | No existing readers — the field was never written by any merged capability (stub never wrote scores). Retype is safe today; deferral is more expensive than landing it now. |
| The `detected_subjects` field is new — no schema validation in the seed corpus | Seed corpus does not have scored historical assets per the Step 0 seed contract; the field defaults to `None` and Pydantic accepts it. No seed change required. |

**Hallucination is the primary risk in Step 4 (as it was in Step 2).** Vector search (Step 3) has wrapper-side ground truth; Vision composition does not — fact-grounding lives only in the prompt + schema. The eval's "detected_subjects subset of key_figures" assertion is the regression net.

---

## Env vars required

| Var | Purpose | Default |
| --- | --- | --- |
| `GOOGLE_API_KEY` | Existing — `google.genai` SDK (now also used for Gemini Vision) | None — required |
| `GEMINI_VISION_MODEL` | Model id for Vision scoring | `gemini-2.5-flash` |
| `GEMINI_EMBEDDING_MODEL` | Existing — Step 3 | `gemini-embedding-2` |
| `GEMINI_NARRATIVE_MODEL` | Existing — Step 2 | `gemini-2.5-flash-lite` |
| `GEMINI_COORDINATOR_MODEL` | Existing — coordinator | `gemini-2.5-flash` |
| `GEMINI_MODEL` | Existing — workflow LLM nodes (default for all non-specific) | `gemini-2.5-flash-lite` |

`GEMINI_VISION_MODEL` is new — defaults to `flash`, not `flash-lite`, because Vision is judgment-laden (interpretive `emotional_score`/`social_score`/`identity_score`) and the named-subject extraction has a hallucination surface that benefits from the stronger model. Documented in the README env section.

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v` | `AssetScores` validates happy-path and rejects out-of-range; `VisionScoringOutput` constructs with scores + detected_subjects; `Asset.scores` accepts `AssetScores` and `None`; `Asset.detected_subjects` accepts `list[str]` and `None`; existing model tests still pass. |
| Wrapper (unit) | `.venv/bin/python -m pytest tests/test_step_4.py -v -k wrapper` | `save_asset_scores` calls mocked client with `update-many`, correct database/collection, filter on `asset_id`, and `$set` containing `scores` (serialized AssetScores), `detected_subjects` (list), and `status: "scored"`. |
| `_score_asset_with_vision` (unit) | `.venv/bin/python -m pytest tests/test_step_4.py -v -k vision_helper` | With a mocked `genai.Client`: helper fetches image bytes, calls `generate_content` with `response_schema=VisionScoringOutput`, parses the response, returns a validated object. Wrong schema response raises. |
| Capability orchestration (unit) | `.venv/bin/python -m pytest tests/test_step_4.py -v -k capability` | `score_assets_with_vision` raises `PreconditionError` when no assets exist; calls `_score_asset_with_vision` once per unscored asset; skips assets that already have `scores`; persists via `save_asset_scores` for each new score; returns the `scored` list with correct shape; tolerates `event_narrative=None`. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0/1/2/3/4 unit tests green. |
| **Trace eval — single run (outcome-shaped)** | `.venv/bin/python -m pytest tests/evals/test_step_4_trace.py -v` | Given an Argentina-vs-France operator prompt with N=3 image fixtures and a seeded narrative + similarity results: (a) coordinator dispatches `run_event_pipeline` exactly once; (b) workflow runs nodes in order: ingest → context → similarity → scoring; (c) mock client recorded 3× `save_asset_scores` `update-many` calls; (d) returned `scored` list has 3 entries each with valid `AssetScores` + `detected_subjects: list[str]`; (e) every `detected_subjects[i]` for every scored asset is a substring of some key_figure name from the seeded narrative (hallucination guard); (f) all five score dimensions are in [0, 1] per asset; (g) at least one asset has at least one score > 0.5 (distributional sanity — catches a regressed Vision returning all-zeros); (h) reasoning text is present in the coordinator's pre-dispatch turn (CoT directive working); (i) on assertion failure, full trace dumped via `dump_trace()`. |
| **Trace eval — pass rate** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_4_trace.py -v` | ≥ 19/20 runs pass all assertions (95% threshold per D-020). |

Step 4's surface exercises **failure categories 1, 3, 4, 5** per `docs/evaluation-strategy.md`: tool selection (dispatch), tool arguments (correct `event_id` propagated through state), tool-output handling (the `detected_subjects` hallucination guard is *category 4*), end-state (scores + detected_subjects persisted with valid structure). Strategy coherence (category 6) does not apply until `propose_review_queue` ships in Step 5.

---

## Output consumed by

- **`propose_review_queue` (capability 5)** — reads `scores` (quality gate + ranking) and `detected_subjects` (identity composition with narrative `key_figures`); refuses queue assembly if absent.
- **`draft_campaigns_for_queue` (capability 6)** — reads `scores` for in-prompt routing-recommendation ranking.
- **The trace** — judges see structured score blocks and per-asset detected_subjects emerge on screen during the demo. This is the "Vision is doing real work" moment.

---

## What changed from prior planning docs

- **Second "computational + LLM" capability** — reuses the `_run_*_llm`-style helper pattern from Step 2 (`_score_asset_with_vision` is the per-asset analog).
- **First per-asset LLM cardinality** — every prior capability called the LLM at most once per dispatch; Step 4 calls it once per unscored asset.
- **`detected_subjects` is new** — promoted from Step 3's risk-table flag (Messi-shots problem) to a formal capability output. Step 5 planning inherits this as input.
- **`Asset.scores` retyped** — from `dict[str, Any]` to `AssetScores | None`. Step 5 inherits the typed contract.
- **New `GEMINI_VISION_MODEL` env var** — separates Vision model from other LLM env vars. Default `gemini-2.5-flash` (not lite — Vision is judgment-laden).

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

These are not optional follow-ups — implementation code in this branch must not contradict the spec it's written against.

1. **New D-entry: `detected_subjects` extraction in Step 4 + identity composition in Step 5** (`tracking.md`).
   Promotes the Messi-shots risk row from `docs/plans/step-3-similarity.md` to a formal architectural decision. Captures: (a) Step 4 extracts `detected_subjects` as the structural fix for cosine's identity-blind behavior; (b) Step 5 composes `detected_subjects` against narrative `key_figures` when assembling the exploitation queue; (c) the field shape is `list[str]` (not structured DetectedSubject); (d) hallucination guard lives in the prompt + eval assertion, not in a typed schema constraint.

2. **New D-entry: `Asset.scores` typed as `AssetScores`** (`tracking.md`).
   Captures the retype from `dict[str, Any] | None` to `AssetScores | None`. Rationale: the typed boundary surfaces malformed score blocks at write time. Trade-off acknowledged: future score-dimension additions become a model change rather than a dict-key addition.

3. **New D-entry: `GEMINI_VISION_MODEL` defaults to `flash`, not `flash-lite`** (`tracking.md`).
   Captures the model-default split. Rationale: D-024's general-purpose workflow default is `flash-lite` for cost; Vision is the first workflow capability that warrants the upgrade because of the hallucination surface on `detected_subjects` + the judgment density of the commercial-signal dimensions.

4. **`docs/specs/02-architecture.md` § `assets` schema update.**
   Add `detected_subjects: list[str] | null` to the `assets` JSON example. Retype `scores` from the inline dict shape to a reference to the new `AssetScores` model. Update the MCP call list under `score_assets_with_vision` to show the actual write (status → "scored", scores set, detected_subjects set).

5. **`docs/db-wrapper-inventory.md` update.**
   `save_asset_scores` row updated to signature `save_asset_scores(asset_id, scores: AssetScores, detected_subjects: list[str]) -> None`. Notes column captures the bundled-write rationale (one update for scores + detected_subjects + status transition).

6. **`docs/specs/01-requirements.md` § `score_assets_with_vision`** — add the `detected_subjects` output to the capability description (one sentence) so the requirements doc reflects the actual contract.

Sequence on this branch:

1. Branch housekeeping commit (items 1–6 above) — doc-only, no code.
2. Plan + tasks gates (this document + the task list).
3. Implementation commits per task ordering.
4. Trace eval and pass-rate gate.
5. Merge to `main` with the updated "Next action" line in `CLAUDE.md`.
