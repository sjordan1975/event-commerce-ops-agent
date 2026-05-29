# Step 6 — Draft Campaigns For Queue: Task List

> Tasks T-6.1 through T-6.13 implement the `draft_campaigns_for_queue` capability per `docs/plans/step-6-drafts.md` — capability 6 of nine. Realized as **one workflow node**, a `FunctionNode` that returns to the Steps 2/4 internal-`genai` pattern (NOT a second `LlmAgent` node — Step 5 is and stays the one strategic node). For each surfaced queue member it generates narrative-grounded copy, derives product/platform/timing, and writes a `campaigns` draft + a `pending` `approvals` entry, transitioning the asset to `status="campaign_draft_created"`. Three new Pydantic models, one new bundled DB wrapper (`submit_campaign_for_review`, new file `src/db/campaigns.py`), two pure helpers, one new prompt, **no new env var** (reuse `GEMINI_MODEL`). Tasks follow the plan's § Dependency order.

Prerequisites:
- Step 5 merged to `main` (`propose_review_queue` live; assets carry persisted `queue_type` / `product_route` / `queue_rank` / `queue_rationale`).
- Branch `step/6-drafts` cut from `main` (already on it).
- Branch housekeeping commit landed (T-6.0 — see below).
- D-024 workflow scaffolding: `build_coordinator()` + `build_workflow()`, `build_pipeline_graph()` chain `(START, ingest, context, similarity, scoring, prepare_queue, propose_review_queue, persist_queue)`, `run_event_pipeline` shim.
- Eval scaffolding from Steps 1–5: `_MockMCPClient` collection-keyed dispatch (write-recording / canned-read), the narrative / similarity / Vision / queue patch surfaces.
- `PreconditionError` from `src/errors.py` reused (no new error type).

Design decisions baked in (rationale in `docs/plans/step-6-drafts.md` + D-030):
- **`FunctionNode` + internal `genai`, not an `LlmAgent` node** (`02-architecture.md`:373). Per-item copy via `_draft_copy_for_asset` (mirror Step 4's `_score_asset_with_vision`); the flanking I/O is the node body.
- **`event_id`-based signature** reading the persisted queue back from Mongo (D-022) — supersedes the stub's `(queue, operator_notes)`.
- **Redraft deferred to Step 7** — `operator_notes` reserved but unused; its contract is defined by Step 7's `request_human_approval` resume payload.
- **Reuse `GEMINI_MODEL`** (flash-lite) — the `build_event_context` precedent (grounded text-gen), no `GEMINI_DRAFT_MODEL` by default.
- **Per-item iteration** (not batched) — grounding isolation + no id echo-back risk; cardinality is small.
- **Copy consumes Step 4's derived signals** (`detected_subjects` as identity/commercial signal, `scores`) + the narrative — **not the raw image**. Grounding granularity = event-narrative + identity, not photographed-action (action shots curated out of the demo corpus).
- **Route → campaign fields**: poster→(poster, shopify), tshirt→(tshirt, shopify), social_only→(None, social), None→(None, social) defensively.
- **`submit_campaign_for_review` is bundled** (three writes, one logical op; not a transaction); approvals created `pending` with empty `reviewer_notes` (never an input).
- **Status transition** `scored → campaign_draft_created` (Step 6's transition; idempotency falls out — re-run no longer matches `status="scored"`).
- **Zero *surfaced* assets is valid-degenerate** (empty result), not a precondition error; only missing event / scored-assets / narrative raise.
- **Eval is Step-4-shaped**: Tier 1 (mocked `_draft_copy_for_asset`, deterministic, single-run authoritative) is the merge gate. An optional live **grounding probe** is a quality check, NOT a pass-rate gate.

---

## T-6.0: Branch housekeeping commit (doc-only)

Doc-only; lands before implementation. Per CLAUDE.md, every `docs/specs/` change needs a `tracking.md` D-entry. Step 6's housekeeping is light — the `campaigns`/`approvals` schemas and `submit_campaign_for_review` already exist in the docs.

1. **D-030** in `tracking.md` — `draft_campaigns_for_queue` as a `FunctionNode` + copy-generation mechanics. All sub-points (a)–(k) from the plan's § Branch housekeeping item 1, **including (j) grounding granularity and (k) the consolidated enterprise trajectory** (operator-framed→data-derived autonomy; two grounding axes; the MongoDB-MCP-as-state-backbone partner framing + additive dual-vector-index).
2. **`docs/specs/02-architecture.md`** — add `GEMINI_MODEL` as the copy node's model in the model-env-var bullet (no new var); note the route→`(product_type, platform_target)` mapping in the `draft_campaigns_for_queue` MCP-call section; note the bundled write is three sequential MCP calls (no transaction) for MVP. (Graph diagram already shows `draft_campaigns_for_queue (FunctionNode)` — no change.)
3. **`docs/db-wrapper-inventory.md`** — confirm `submit_campaign_for_review(campaign) -> {campaign_id, approval_id}`; drop any `reviewer_notes` input from the signature.
4. **`docs/safety-measures.md`** — note the copy node carries `max_output_tokens` (per-item, sized for one headline+caption+hashtags) per the Gap 2 spend bound.
5. **`docs/specs/01-requirements.md` § `draft_campaigns_for_queue`** — one sentence: the redraft *implementation* lands in Step 7 (the capability surface reserves it; this branch implements first-pass drafting).

Verify: `git show <housekeeping-sha> --stat` shows only doc files; no `src/` or `tests/` changes.

---

## T-6.1: Add the `GeneratedCopy` model (LLM output schema)

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `GeneratedCopy(BaseModel)` — **no** `extra="forbid"` (Gemini `response_schema` rejects `additionalProperties:false`, per Steps 2/4/5). Fields: `headline: str`, `caption: str`, `hashtags: list[str]`.
- Tests: happy-path construction; round-trips through `model_validate_json` (the `response_schema` path); empty `hashtags` list is valid; missing `headline` rejected (required).

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k generated_copy`

---

## T-6.2: Add the `Campaign` and `Approval` models (persisted documents)

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `Campaign(BaseModel)` — `model_config = ConfigDict(extra="forbid")` (persisted doc, like `Event`/`Asset`). Fields: `campaign_id: str`, `asset_id: str`, `event_id: str`, `product_type: Literal["poster", "tshirt"] | None`, `generated_copy: GeneratedCopy`, `platform_target: Literal["shopify", "printful", "social"]`, `timing_recommendation: str`, `status: str = "draft"`, `created_at: str`, `execution: dict | None = None`.
- `Approval(BaseModel)` — `extra="forbid"`. Fields: `approval_id: str`, `campaign_id: str`, `asset_id: str`, `status: str = "pending"`, `reviewer_notes: str | None = None`, `created_at: str`, `decided_at: str | None = None`.
- Tests: happy-path construction; `product_type=None` accepted (social_only); `platform_target` rejects a value outside the three literals; `product_type` rejects a value outside `poster`/`tshirt`/None; `extra="forbid"` rejects an unknown field; defaults (`status`, `execution`, `reviewer_notes`, `decided_at`) apply.

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k "campaign or approval"` and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green).

---

## T-6.3: Extend conftest helpers

Files: `tests/conftest.py`
Acceptance: Three helpers following the `**overrides` pattern:
- `build_valid_generated_copy(**overrides) -> GeneratedCopy` — defaults: `headline="Messi caps Argentina's extra-time upset"`, `caption="The night Argentina ended France's reign — limited edition print."`, `hashtags=["#WorldCup2026", "#ArgentinaVsFrance"]`.
- `build_valid_campaign(**overrides) -> Campaign` — defaults: `campaign_id="cmp-1"`, `asset_id="a1"`, `event_id="evt-demo-1"`, `product_type="poster"`, `generated_copy=build_valid_generated_copy()`, `platform_target="shopify"`, `timing_recommendation="2026-07-14T22:00:00Z"`, `status="draft"`, `created_at=<iso>`, `execution=None`.
- `build_valid_approval(**overrides) -> Approval` — defaults: `approval_id="apr-1"`, `campaign_id="cmp-1"`, `asset_id="a1"`, `status="pending"`, `reviewer_notes=None`, `created_at=<iso>`, `decided_at=None`.

Verify: `.venv/bin/python -c "from tests.conftest import build_valid_campaign, build_valid_approval; from src.models import Campaign, Approval; assert isinstance(build_valid_campaign(), Campaign) and build_valid_approval().status=='pending'; print('ok')"`

---

## T-6.4: Implement `submit_campaign_for_review` wrapper (bundled write)

Files: `src/db/campaigns.py` (new), `tests/test_step_6.py` (new file)
Acceptance: `submit_campaign_for_review(campaign: Campaign) -> dict` is async. One logical operation, three MCP calls (no transaction):
- `approval_id = str(uuid4())`.
- `campaigns insert-many`: `[campaign.model_dump(mode="json")]`.
- `assets update-many`: `filter={"asset_id": campaign.asset_id}`, `update={"$set": {"status": "campaign_draft_created", "campaign_id": campaign.campaign_id}}`.
- `approvals insert-many`: `[{"approval_id": approval_id, "campaign_id": campaign.campaign_id, "asset_id": campaign.asset_id, "status": "pending", "reviewer_notes": None, "created_at": <iso>, "decided_at": None}]`.
- Returns `{"campaign_id": campaign.campaign_id, "approval_id": approval_id}`.
- All `get_client().call(...)` use `"database": "event_commerce"`.

Unit test monkeypatches `src.db.campaigns.get_client`; asserts: (a) all three writes issued with correct `(database, collection)`; (b) the `assets` `$set` is exactly `{status, campaign_id}` (status `campaign_draft_created`); (c) the `approvals` doc is `pending` with `reviewer_notes=None` and `decided_at=None`; (d) **`reviewer_notes` is not a parameter** of the function (signature check); (e) returns both ids.

Verify: `.venv/bin/python -m pytest tests/test_step_6.py -v -k submit`

---

## T-6.5: Implement pure helpers `_route_to_campaign_fields` + `_recommend_timing`

Files: `src/capabilities/drafts.py` (extend; the file currently holds the stub), `tests/test_step_6.py` (extend)
Acceptance:
- `_route_to_campaign_fields(product_route: str | None) -> tuple[str | None, str]` — pure. `poster → ("poster", "shopify")`; `tshirt → ("tshirt", "shopify")`; `social_only → (None, "social")`; `None → (None, "social")` (defensive — a surfaced item that left `product_route` unset is treated as social_only, not an error).
- `_recommend_timing(timeliness: float, event) -> str` — pure, deterministic. Returns an ISO-8601 string; higher `timeliness` → sooner recommendation (e.g. now for high timeliness, a timeliness-scaled offset otherwise). Exact formula at implementer's discretion but must be deterministic and unit-testable.

Unit tests: `_route_to_campaign_fields` all four cases (incl. None); `_recommend_timing` deterministic (same inputs → same output) and monotonic in timeliness (higher timeliness is not later than lower).

Verify: `.venv/bin/python -m pytest tests/test_step_6.py -v -k "route or timing"`

---

## T-6.6: Add the draft-copy prompt template

Files: `prompts/v3/draft_campaign_copy.md` (new)
Acceptance: New prompt under `v3`. Content matches the plan's § "Draft-copy prompt template" — sections: EVENT NARRATIVE (`{narrative_angle}`, `{key_figures}`); THIS ASSET (`{queue_rationale}`, `{product_route}`, `{detected_subjects}`); WRITE THE COPY with: headline grounded in the narrative angle ("specific, not generic" + worked example), the **GROUNDING GUARD** (name only subjects in `detected_subjects`; do not name a key figure absent from this frame; do not describe a specific action/pose/moment), caption, hashtags. Format placeholders: `{narrative_angle}`, `{key_figures}`, `{queue_rationale}`, `{product_route}`, `{detected_subjects}`.

Loaded via existing `load_prompt("draft_campaign_copy")` — no loader change.

Verify: `.venv/bin/python -c "from src.prompt_loader import load_prompt; t=load_prompt('draft_campaign_copy'); assert 'GROUNDING GUARD' in t and 'detected_subjects' in t and '{narrative_angle}' in t and '{detected_subjects}' in t; print('ok')"`

---

## T-6.7: Implement `_draft_copy_for_asset` internal helper + eval-mock seam

Files: `src/capabilities/drafts.py` (extend), `tests/test_step_6.py` (extend)
Acceptance: `_draft_copy_for_asset(narrative_context: dict, item_context: dict) -> GeneratedCopy` — sync (callers wrap in `asyncio.to_thread`), mirroring Step 4's `_score_asset_with_vision`:
- `model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")` (**no** new env var).
- Builds the prompt: `load_prompt("draft_campaign_copy").format(narrative_angle=..., key_figures=..., queue_rationale=..., product_route=..., detected_subjects=...)`.
- `genai.Client(api_key=os.environ["GOOGLE_API_KEY"]).models.generate_content(model=model, contents=[prompt], config=GenerateContentConfig(response_mime_type="application/json", response_schema=GeneratedCopy, max_output_tokens=<bounded>))`.
- Returns `GeneratedCopy.model_validate_json(response.text)`.
- This function is the **eval-mock seam** — Tier 1 patches it (analogous to patching `_score_asset_with_vision`).

Unit test: patch `genai.Client` (or assert prompt construction); confirm the prompt embeds the narrative angle + detected_subjects, and `model_validate_json` parses a canned response into `GeneratedCopy`. (No live call in unit tests.)

Verify: `.venv/bin/python -m pytest tests/test_step_6.py -v -k draft_copy_helper`

---

## T-6.8: Implement `draft_campaigns_for_queue` capability

Files: `src/capabilities/drafts.py` (replace stub), `tests/test_step_6.py` (extend)
Acceptance: `draft_campaigns_for_queue(event_id: str, operator_notes: dict | None = None) -> dict` is async:
- `event = await get_event(event_id)`; if `None` → `raise PreconditionError(capability="draft_campaigns_for_queue", context=event_id, missing={"event": "event not found; call ingest_event_batch first"})`.
- `scored = await get_assets_for_event(event_id, status="scored")`. Build `missing`: if not `scored` → `missing["scores"]="no scored assets; call score_assets_with_vision first"`; if `event.event_narrative is None` → `missing["narrative"]="call build_event_context first"`. If `missing` → raise `PreconditionError`.
- `queued = [a for a in scored if a.queue_type is not None]`, ordered by `(queue_type, queue_rank)`. **If `not queued` → return `{"event_id": event_id, "campaign_ids": [], "approval_ids": [], "drafts": []}`** (zero surfaced = valid-degenerate, NOT an error).
- `narrative_context = {"narrative_angle": ..., "key_figures": <comma-joined names>}` from `event.event_narrative`.
- Per queued asset: `item_context = {"queue_rationale": a.queue_rationale, "product_route": a.product_route, "detected_subjects": a.detected_subjects or []}`; `copy = await asyncio.to_thread(_draft_copy_for_asset, narrative_context, item_context)`; `product_type, platform_target = _route_to_campaign_fields(a.product_route)`; build `Campaign(...)` (`campaign_id=str(uuid4())`, `timing_recommendation=_recommend_timing(event.timeliness, event)`, `status="draft"`, `created_at=<iso>`, `execution=None`); `result = await submit_campaign_for_review(campaign)`; collect `campaign_ids`, `approval_ids`, and a `drafts` entry `{asset_id, product_route, headline, caption, timing_recommendation, queue_rationale}`.
- `operator_notes` is **reserved but unused** (docstring: redraft branch lands in Step 7 with the HITL loop that defines the payload).
- Returns `{"event_id", "campaign_ids", "approval_ids", "drafts"}`.

Unit tests (mock `_draft_copy_for_asset` to return a canned `GeneratedCopy`; mock `submit_campaign_for_review`; mock `get_event` / `get_assets_for_event`): one draft per queued asset; un-surfaced (`queue_type=None`) assets skipped; **zero-surfaced (scored assets exist, none queued) returns the empty result without raising**; preconditions raise with the right `missing` keys on missing event / no scored assets / `event_narrative=None`; route mapping flows into the built `Campaign` (poster→shopify, social_only→None/social).

Verify: `.venv/bin/python -m pytest tests/test_step_6.py -v -k draft_campaigns`

---

## T-6.9: Wire adapter + node + graph edge

Files: `src/capabilities/__init__.py` (modify), `tests/test_step_6.py` (extend)
Acceptance:
- Import `draft_campaigns_for_queue` from `src.capabilities.drafts`.
- Adapter `_node_draft_campaigns_for_queue(ctx)`: reads `event_id = ctx.state["event_id"]`; `result = await draft_campaigns_for_queue(event_id)`; writes `ctx.state["campaign_ids"] = result["campaign_ids"]`, `ctx.state["approval_ids"] = result["approval_ids"]`, `ctx.state["drafts"] = result["drafts"]`; returns `result`.
- `draft_campaigns_for_queue_node = FunctionNode(func=_node_draft_campaigns_for_queue, name="draft_campaigns_for_queue", parameter_binding="state")`.
- Extend the `build_pipeline_graph()` chain tuple to **9 elements**: `(START, ingest, context, similarity, scoring, prepare_queue, propose_review_queue, persist_queue, draft_campaigns_for_queue_node)`. Update the module + function docstrings ("Current pipeline" line) to include the new node; drop the "Step 6 → adds draft_campaigns_for_queue" future line.

Unit tests: adapter exists and writes `campaign_ids`/`approval_ids`/`drafts` to state (mock `draft_campaigns_for_queue`); `draft_campaigns_for_queue_node.name == "draft_campaigns_for_queue"`.

Verify: `.venv/bin/python -m pytest tests/test_step_6.py -v -k node_adapter` and `.venv/bin/python -c "from src.capabilities import draft_campaigns_for_queue_node; print('ok')"`

---

## T-6.10: Extend `run_event_pipeline` return + coordinator prompt

Files: `src/agent.py` (modify), `prompts/v3/coordinator_system.md` (light edit)
Acceptance:
- `run_event_pipeline` adds `"campaign_ids": state.get("campaign_ids")`, `"approval_ids": state.get("approval_ids")`, `"drafts": state.get("drafts")` to its returned dict.
- `prompts/v3/coordinator_system.md`: one-line addition — after `run_event_pipeline` returns, present the generated campaign drafts (per item: headline, product route, timing recommendation) alongside the proposed review queue. (No other coordinator change.)

Verify: `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green — graph builds with the 9-element chain; no regressions).

---

## T-6.11: Extend trace-eval scaffolding (pre-seed queue-bearing assets + `_draft_copy_for_asset` mock control)

Files: `tests/evals/conftest.py` (modify)
Acceptance: Per the plan's § Eval scaffolding decision — the `_MockMCPClient` is write-recording / canned-read, so Step 6's read of persisted queue fields must be **pre-seeded**, not produced by Step 5's write path:
1. **Pre-seed queue-bearing assets.** Register an `assets` `find` handler that, for the `status="scored"` filter, returns assets already carrying `status="scored"` + `queue_type` (exploitation/discovery) + `product_route` + `queue_rank` + `queue_rationale` + `scores` + `detected_subjects`. The seed **spans routes** — at least one `poster`, one `tshirt`, one `social_only` member (so route-mapping assertion T1-d is meaningful) — and includes **one un-surfaced asset** (`queue_type=None`, so the skip assertion T1-c has something to skip) and **one with empty `detected_subjects`** (a crowd shot, for the grounding probe's hallucination guard, T-6.13). Upstream surfaces (narrative / similarity / Vision / queue) stay patched as in Steps 2–5 so a full dispatch flows into Step 6.
2. **`_draft_copy_for_asset` mock control.** A fixture / context-manager that patches `src.capabilities.drafts._draft_copy_for_asset` to return a canned `GeneratedCopy` (Tier 1), or leaves it live (grounding probe).

Verify: `.venv/bin/python -m pytest tests/evals/test_mock_dispatch.py -v` (existing green) + a new mock-dispatch test asserting the pre-seeded `status="scored"` handler returns route-spanning queued assets and the `_draft_copy_for_asset` patch round-trips.

---

## T-6.12: Tier 1 — plumbing eval (deterministic, mocked, CI ship gate)

Files: `tests/evals/test_step_6_trace.py` (new)
Acceptance: Full `run_event_pipeline` dispatch with `_draft_copy_for_asset` **patched** (zero live calls), upstream patched + queue-bearing assets pre-seeded per T-6.11. Same Argentina-vs-France operator prompt as Steps 2–5. Single run is authoritative (deterministic). Assertions:
- (T1-a) one `campaigns insert-many` per queued asset, carrying the canned copy and the correct `product_type`/`platform_target` for each asset's route.
- (T1-b) one `approvals insert-many` per draft, `status="pending"`, linked `campaign_id`/`asset_id`, `reviewer_notes=None`.
- (T1-c) each drafted asset's `assets update-many` set `status="campaign_draft_created"` + `campaign_id`; the un-surfaced (`queue_type=None`) asset got **no** campaign/approval/status write.
- (T1-d) route mapping correct across the seeded `poster` / `tshirt` / `social_only` members.
- (T1-e) coordinator dispatched `run_event_pipeline` exactly once; reasoning text present pre-dispatch (CoT directive); the return carries `campaign_ids`/`approval_ids`/`drafts`. On failure `dump_trace()`.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_6_trace.py -v` (runs offline, no `GOOGLE_API_KEY` needed). **This is the gate `main` stays green against.**

---

## T-6.13: Optional grounding probe (live, deliberate — NOT a merge gate)

Files: `tests/evals/test_step_6_grounding.py` (new)
Acceptance: Runs the real `_draft_copy_for_asset` (live, `GOOGLE_API_KEY` required) against the seeded narrative whose key-figure name / angle term is known. **Quality probe, not a pass-rate gate** — no `EVAL_REPEAT=20`, no transient-error-exclude machinery (copy-gen has no judgment-infra flakiness once mocked; this is a deliberate quality check). Assertions:
- (a) **Grounding** — for an asset whose `detected_subjects` contains the key figure, the generated headline or caption contains that token (the key-figure surname or a distinctive angle term) — copy is grounded, not generic.
- (b) **Hallucination guard** — for the seeded **empty-`detected_subjects`** asset (crowd shot), the copy does **not** name a key figure absent from that frame.
- On failure `dump_trace()`.

If the probe reveals generic copy or guard violations, climb the remediation ladder per `docs/evaluation-strategy.md` — prompt language first (strengthen the grounding rubric / GROUNDING GUARD); the model-swap rung introduces `GEMINI_DRAFT_MODEL=flash` (on evidence, not by default). **Never** a heuristic. Run deliberately (validating demo copy quality) — **not** on offline code-CI and **not** a merge blocker.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_6_grounding.py -v` (requires `GOOGLE_API_KEY`).

---

## Verification checkpoints (rollup — Tier 1 + unit suite must pass before merge)

| After | Command | Must pass |
| --- | --- | --- |
| T-6.1 / T-6.2 | `.venv/bin/python -m pytest tests/test_models.py -v -k "generated_copy or campaign or approval"` | `GeneratedCopy` (no forbid) round-trips; `Campaign`/`Approval` (forbid) validate + reject bad enums/extras; `product_type=None` accepted. |
| T-6.4 (wrapper) | `.venv/bin/python -m pytest tests/test_step_6.py -v -k submit` | Three writes; `assets` `$set` = {status `campaign_draft_created`, campaign_id}; `approvals` pending + `reviewer_notes=None`; no `reviewer_notes` param. |
| T-6.5 (helpers) | `.venv/bin/python -m pytest tests/test_step_6.py -v -k "route or timing"` | Route mapping all four cases; timing deterministic + monotonic. |
| T-6.7 / T-6.8 | `.venv/bin/python -m pytest tests/test_step_6.py -v -k "draft_copy_helper or draft_campaigns"` | Helper builds prompt + parses; capability: one draft per queued asset, un-surfaced skipped, zero-surfaced → empty result, preconditions raise on missing event / scored-assets / narrative. |
| T-6.9 / T-6.10 (wiring) | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Graph builds with the 9-element chain incl. `draft_campaigns_for_queue`. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–6 unit tests green; no regression. |
| **Tier 1 — plumbing gate (CI)** | `.venv/bin/python -m pytest tests/evals/test_step_6_trace.py -v` | Deterministic; (T1-a)–(T1-e); offline, no API key. The gate `main` stays green against. |
| Grounding probe (optional, deliberate) | `.venv/bin/python -m pytest tests/evals/test_step_6_grounding.py -v` | Grounding token present; hallucination guard holds. **Quality probe, not a merge gate** (requires `GOOGLE_API_KEY`). |

---

## Notes on task granularity

- T-6.1 / T-6.2 split: `GeneratedCopy` (LLM output schema, **no** `extra="forbid"`) is a different failure mode from `Campaign`/`Approval` (persisted docs, `extra="forbid"`). The split mirrors Step 5's QueueItem-vs-Asset split and keeps the `extra="forbid"` discipline legible.
- T-6.4 is one task — the three writes are one inseparable bundled domain operation (db-wrapper-inventory § "bundling is correct here"); splitting them would fragment a single atomic unit.
- T-6.5 bundles the two pure helpers — both small, deterministic, no I/O, same test file section.
- T-6.7 / T-6.8 split: the internal `genai` helper (the mock seam) is independently testable from the capability that loops it + drives the bundled write + enforces preconditions.
- T-6.9 / T-6.10 split: adapter + node instance are unit-testable; the graph-edge + `run_event_pipeline` + coordinator-prompt change is the integration layer exercised by the build-smoke + full suite.
- T-6.12 / T-6.13 split: Tier 1 (deterministic, mocked, the merge gate) and the grounding probe (live, deliberate, non-gating) are different artifacts, commands, and CI posture — this split is the Step-4-shaped eval decision (D-030).

---

## What is intentionally not in this step

- **No redraft / `operator_notes` implementation.** Reserved in the signature; the branch + its payload contract land in Step 7 with the HITL loop.
- **No HITL.** `request_human_approval` (Step 7) reads the `pending` approvals this step writes.
- **No execution.** `campaigns`/`assets` execution fields + `published_urls` are written by `execute_approved_campaigns` (Step 7).
- **No new model env var.** Copy runs on `GEMINI_MODEL`; `GEMINI_DRAFT_MODEL` is an evidence-gated remediation rung, not a default.
- **No image sent to the copy LLM.** Copy consumes derived signals + narrative (MVP grounding boundary); the perception-layer `scene_description` is an enterprise-trajectory note (D-030), not Step 6 work.
- **No live model in the CI gate.** Tier 1 is mocked; live grounding lives in the optional probe, run deliberately.
- **No second `LlmAgent` node.** `draft_campaigns_for_queue` is a `FunctionNode`; Step 5 remains the one strategic node.
- **No enforced multi-route.** One campaign per asset (MVP); multi-route is the enterprise path.
