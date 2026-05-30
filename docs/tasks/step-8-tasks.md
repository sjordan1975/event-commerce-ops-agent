# Step 8 — `record_outcomes`: Task List

> Tasks T-8.0 through T-8.10 implement capability **9 (`record_outcomes`)** — the 9th and **final** capability — per `docs/plans/step-8-outcomes.md`. Like Step 7, it lives **coordinator-side** and adds **zero workflow nodes** (`build_pipeline_graph()` stays at 9). Step 7 left the executed set as published `assets` + executed `campaigns`; Step 8 writes one **provenance** `performance` row per published asset (true linkage + 7-day window anchor + `metrics: null`, `metrics_status: "pending_sync"`) and the coordinator then reports and stops. **Thin, honest coda — no fabricated metrics.** Tasks follow the plan's § Dependency order.

Prerequisites:
- Step 7 merged to `main` (`execute_approved_campaigns` live; published `assets` carry `status="published"` + `published_urls`; executed `campaigns` carry `status="executed"` + `execution` with `executed_at`).
- Branch `step/8-outcomes` cut from `main` (already on it).
- Branch housekeeping commit landed (T-8.0 — see below).
- D-024/D-031 scaffolding: `build_coordinator()` registers `run_event_pipeline`, `request_human_approval`, `apply_approval_decisions`, `redraft_campaigns`, `execute_approved_campaigns`; the clarification sub-agent; the graph is built by `build_pipeline_graph()` (9 nodes, **unchanged this step**).
- Existing reusable readers: `get_assets_for_event(event_id, status=...)` (`src/db/assets.py`:26), `get_campaigns_by_ids(ids)` (`src/db/campaigns.py`:153).
- Existing performance reader (built Step 2, **modified this step**): `aggregate_performance_for_events(event_ids)` (`src/db/performance.py`:14), called by `build_event_context` (`src/capabilities/context.py`:81).

Design decisions baked in (rationale in `docs/plans/step-8-outcomes.md` + D-032):
- **Thin honest coda — descope, not removal (Hard Constraint #1).** Capability 9 runs end-to-end but writes a **provenance record only**: `metrics: null`, `metrics_status: "pending_sync"`. No fabricated sales. The rich version (real outcomes ingested async over the 7-day window) is the named **enterprise path**. **Blessed at the human gate 2026-05-29.**
- **Null, not zero.** `metrics: null` = "not yet measured"; `{orders: 0}` would be a false claim nothing sold.
- **Protect the Step-2 spine from this step's own writes.** Pending provenance docs land in the **same** `performance` collection the Step-2 baseline aggregates read. The reader **must honor the discriminator** — `aggregate_performance_for_events` excludes `metrics_status == "pending_sync"` so the baseline stays *measured-only*. This is a deliberate **retro into Step-2-owned code** (the `metrics_status` field doesn't exist until this step, so the reader can only be taught now). Filter is `$ne: "pending_sync"` (exclude-the-pending) **not** `$eq: "synced"` — so seeded/legacy docs with **no** status field are *kept* (backward-compatible).
- **No LLM call, no external API call** — the first purely-computational coordinator capability. Bounded computation end-to-end.
- **Execute + record are sibling coordinator `FunctionTool`s, NOT a post-approval Workflow** (resolves the Step-7 D-031(h) flag). Graph-wiring would reopen D-031(a) for a trivial 2-node graph; the D-023 order-tension is mitigated by the prompt + a **tool-level no-op guard** (`record_outcomes` finds nothing and no-ops if called before execute — robust to LLM mis-ordering).
- **Idempotent upsert** by `(asset_id, event_id)` — execution is *retriable* (Step 7), so a re-run of execute→record must not double-write. **Deviation from the inventoried `insert-many`** (recorded in D-032).
- **Window anchor** = the campaign's `execution.executed_at` (publish time; spec: "7 days from `published_at`"). `recorded_at` = now. Defensive fallback to `recorded_at` if `executed_at` absent.
- **`get_top_performers_by_channel` deferred** (designed-not-built) — demo-storytelling polish; bolts on later with zero retrofit cost. **Blessed at the human gate 2026-05-29.**
- **Eval is single-part** — one deterministic mocked **Tier-1 trace eval** (the merge gate) extending the Step-7 round-trip through `record_outcomes`. No behavioral repetition probe (no protocol-order risk beyond "record after execute," which the no-op guard backstops).

---

## T-8.0: Branch housekeeping commit (doc-only)

Doc-only; lands before implementation. Per CLAUDE.md, every `docs/specs/` change needs a `tracking.md` D-entry. **This step's housekeeping is corrective** — the "synthetic metrics" framing is stale across several docs.

1. **D-032** in `tracking.md` — `record_outcomes` thin honest coda. Capture all sub-points from the plan's § Branch housekeeping item 1: (a) **descope-to-coda, not removal** — provenance record (`metrics: null` + `metrics_status: "pending_sync"`); no fabrication; rich version is the named external-sync enterprise path (frame vs. Hard Constraint #1; **blessed at the human gate**); (b) **spine protection** — pending docs excluded from `aggregate_performance_for_events` so the Step-2 baseline stays measured-only; the discriminator is a **contract on the `performance` collection** — any *future* reader (deferred `get_top_performers_by_channel`, enterprise sync queries) must also honor it; (c) **execute+record are sibling coordinator `FunctionTool`s, not a post-approval Workflow** (resolves D-031(h)) — declining would reopen D-031(a); D-023 order-tension mitigated by prompt + tool-level no-op guard; (d) **idempotent upsert** by `(asset_id, event_id)` — deviation from inventoried `insert-many`; (e) **no LLM call** — first purely-computational coordinator capability; (f) supersedes the "synthetic metrics" framing in `01-requirements.md`:261 / `_step-8-notes.md` § Honesty caveats item 1 / `agentic-model.md`:103. Refines D-031, D-022, D-016/D-021. Mark `get_top_performers_by_channel` **deferred** (designed-not-built; blessed at the gate).
2. **`docs/specs/01-requirements.md`:261** — correct capability 9's description: provenance/pending, **not** "written simultaneously as synthetic values." Confirm the 7-day window is the *measurement* window the external sync fills.
3. **`docs/specs/02-architecture.md`** — annotate the `performance` schema (`146-168`): MVP writes `metrics: null` + `metrics_status`; the zeroed example is the *measured* shape the sync populates. Fix the `record_outcomes` MCP block (`311-315`): `performance` **upsert** (not `insert-many`); the `assets.aggregate` "find best performers" line is the deferred `get_top_performers_by_channel` (not built this step).
4. **`docs/db-wrapper-inventory.md`:229-236** — update `record_performance` signature (adds `product_route`, `window_start`; `metrics` defaults `None`; **upsert** not `insert-many`); mark `get_top_performers_by_channel` deferred.
5. **`CLAUDE.md`** — § Current Phase "Next action" → Step 8 plan + tasks written, implementation next; note `record_outcomes` registered as a coordinator `FunctionTool` (second coordinator-plane step; graph still 9 nodes). (Final "Next action" merge update lands at T-8.10.)

Verify: `git show <housekeeping-sha> --stat` shows only doc files (`tracking.md`, `docs/`, `CLAUDE.md`); no `src/` or `tests/` changes.

---

## T-8.1: Add Step 8 models

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `PerformanceMetrics(BaseModel)` — the future measured shape (written `None` by the coda; populated by the enterprise sync). Fields: `shopify: dict | None = None`, `printful: dict | None = None`, `social: dict | None = None`. **No** `extra="forbid"`.
- `Performance(BaseModel)` — the persisted provenance doc. `model_config = ConfigDict(extra="forbid")`. Fields: `performance_id: str`, `asset_id: str`, `campaign_id: str`, `event_id: str`, `product_route: str | None`, `channels: list[str]`, `metrics: PerformanceMetrics | None = None`, `metrics_status: Literal["pending_sync", "synced"] = "pending_sync"`, `window_days: int = 7`, `window_start: str | None`, `recorded_at: str`.
- Tests: `Performance` validates a full doc, rejects an unknown field (`extra="forbid"`), defaults `metrics=None` / `metrics_status="pending_sync"` / `window_days=7`; `metrics_status` rejects a 3rd value; `PerformanceMetrics` round-trips with all-None and with populated channel dicts.

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k "performance"`

---

## T-8.2: Extend conftest helpers

Files: `tests/conftest.py` (extend)
Acceptance:
- `build_valid_performance(**overrides) -> Performance` — returns a valid provenance doc (e.g. `channels=["shopify","printful"]`, `metrics=None`, `metrics_status="pending_sync"`, `window_days=7`, a `window_start` ISO string, a `recorded_at` ISO string). Follows the existing `build_valid_*` override-merge pattern.

Verify: `.venv/bin/python -c "from tests.conftest import build_valid_performance; print(build_valid_performance().metrics_status)"` → `pending_sync`

---

## T-8.3: `record_performance` (idempotent upsert) + `channels_for_route`

Files: `src/db/performance.py` (extend), `tests/test_step_8.py` (new)
Acceptance:
- `channels_for_route(product_route: str | None) -> list[str]` — `poster`/`tshirt` → `["shopify", "printful"]`; `social_only`/`None`/anything else → `["social"]`. (Same `product_route` channel map as Step 7 execution, D-030.)
- `record_performance(asset_id, campaign_id, event_id, product_route, window_start, metrics=None) -> None` — builds a `Performance` doc: `performance_id` deterministic from `(asset_id, event_id)` (stable upsert key), `channels=channels_for_route(product_route)`, `metrics_status="synced" if metrics else "pending_sync"`, `window_days=7`, `recorded_at=now_iso()`. Persists via `update-many` with `filter={asset_id, event_id}`, `update={"$set": doc}`, `upsert=True`.
- Tests (mocked client, write-recording): writes the expected `$set` payload; `metrics=None` → `metrics_status="pending_sync"`; channel breakdown matches route (poster → shopify+printful; social_only → social); **idempotency** — two calls for the same `(asset_id, event_id)` both issue `upsert=True` on the same filter (no second distinct doc); `window_start` is carried through.

Verify: `.venv/bin/python -m pytest tests/test_step_8.py -v -k "record_performance or channels"`

---

## T-8.4: Spine fix — exclude pending docs from the Step-2 baseline  *(modifies Step-2-owned code)*

Files: `src/db/performance.py` (modify `aggregate_performance_for_events`), `tests/test_step_8.py` (extend)
Acceptance:
- Prepend `{"$match": {"metrics_status": {"$ne": "pending_sync"}}}` to the `aggregate_performance_for_events` pipeline (before the existing `$match` on `event_id`, or merged into it). **Exclude-the-pending**, not include-only-synced — so seeded/legacy docs with no `metrics_status` field are *kept*.
- **Pending-neutral regression test** (deterministic, binary): `aggregate_performance_for_events` returns **identical** output whether or not `pending_sync` docs are present in the collection — i.e. a fixture with measured docs only vs. the same measured docs + extra `pending_sync` docs produces the same `top_product_route` / `total_orders` / `asset_count`.
- **No Step-2 regression:** existing `tests/test_step_2.py` aggregate tests pass unchanged (their fixtures carry no `metrics_status`, so the new `$match` is a no-op for them).

Verify:
- `.venv/bin/python -m pytest tests/test_step_8.py -v -k "baseline or pending_neutral"`
- `.venv/bin/python -m pytest tests/test_step_2.py -v -k "aggregate or performance"` (unchanged green)

---

## T-8.5: `record_outcomes` capability + no-op guard

Files: `src/capabilities/outcomes.py` (new), `tests/test_step_8.py` (extend)
Acceptance:
- `record_outcomes(event_id: str, tool_context: ToolContext) -> dict`:
  1. `published = await get_assets_for_event(event_id, status="published")`.
  2. **No-op guard:** if `published` is empty → return `{"status": "nothing_to_record", "event_id": event_id}` (no writes).
  3. `campaigns = await get_campaigns_by_ids([a.campaign_id for a in published])`; index by `campaign_id`.
  4. Per published asset: `window_start = (campaign.execution or {}).get("executed_at")` (fallback `None` → `record_performance` defaults to `recorded_at`); call `record_performance(asset_id, campaign_id, event_id, product_route, window_start, metrics=None)`.
  5. Return `{"status": "recorded", "event_id", "count": N, "pending_sync": True, "records": [{asset_id, campaign_id, channels}, ...]}`.
- One-line docstring per the plan's § Tool docstring (post-execute precondition, no-fabrication truth, no-op behavior, terminal-after cue).
- Tests (mocked client + seeded published assets/executed campaigns): one provenance doc per published asset; correct `(asset_id, campaign_id, event_id)` linkage; `channels` by route; `window_start` pulled from `campaign.execution.executed_at`; **no-op guard** returns `nothing_to_record` and writes nothing when no published assets; **idempotency** — second call upserts, does not duplicate.

Verify: `.venv/bin/python -m pytest tests/test_step_8.py -v -k "record_outcomes"`

---

## T-8.6: Register `record_outcomes` in the coordinator

Files: `src/agent.py` (`build_coordinator`)
Acceptance:
- Import `record_outcomes` from `src.capabilities.outcomes`.
- Add `FunctionTool(record_outcomes)` to the `tools` list in `build_coordinator()` (alongside the existing five coordinator tools).
- No change to the graph, the clarification sub-agent, or `build_workflow()`.

Verify: `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` → `ok`

---

## T-8.7: Coordinator prompt — post-execute step (small edit)

Files: `prompts/v3/coordinator_system.md`
Acceptance:
- § "What you do": replace the current step 8 ("Report. After execution… stop.") with two ordered steps:
  - **8. Record outcomes.** After `execute_approved_campaigns` returns, call `record_outcomes(event_id)` **exactly once**. This opens the performance-tracking record for each published asset (metrics are synced later, not now).
  - **9. Report.** Say briefly: how many items published, how many rejected, any failures, and that outcomes are now **tracked and pending performance sync**. Then stop. **Do NOT claim sales or engagement numbers — none exist yet.**
- § "Post-approval protocol": add the `record_outcomes` call to the end of the execute branch ("…→ `execute_approved_campaigns(event_id)` once → `record_outcomes(event_id)` once → report").
- Honest terminal text — no fabricated metrics in the report (correcting, not editing, `agentic-model.md`:103's "metrics recorded" example).
- No `PROMPT_VERSION` bump (in-place v3 edit, consistent with Step 7's prompt edits).

Verify: `grep -n "record_outcomes" prompts/v3/coordinator_system.md` shows the post-execute step + the protocol branch; `.venv/bin/python -c "from src.prompt_loader import load_prompt; assert 'record_outcomes' in load_prompt('coordinator_system'); print('ok')"`

---

## T-8.8: Eval conftest extension

Files: `tests/evals/conftest.py` (modify)
Acceptance:
- Register **one** `(update-many, performance)` handler (write-recording — captures the upsert payloads for assertion).
- Ensure a `(find, assets)` handler returns the seeded **published** assets for the event (status filter honored). Per the **mock-handler-clobber** rule: this `(tool, collection)` pair is distinct from the existing `(aggregate, performance)` handler, so **no clobber** — but if any existing `(find, assets)` handler is reused, extend the **single** combined handler to branch on the `status="published"` filter rather than registering a second.
- Seed `campaigns` (executed, with `execution.executed_at`) reachable by `get_campaigns_by_ids` for the window anchor.

Verify: covered by T-8.9 (the trace eval exercises these handlers).

---

## T-8.9: Tier-1 trace eval — extend the Step-7 round-trip through `record_outcomes`

Files: `tests/evals/test_step_8_trace.py` (new)
Acceptance: deterministic, mocked (no `GOOGLE_API_KEY`, no Shopify/Printful); extends the Step-7 round-trip (dispatch → suspend → resume → apply → execute) through `record_outcomes`. Asserts:
- **(T1-a)** after `execute_approved_campaigns`, the coordinator calls `record_outcomes(event_id)` **exactly once**.
- **(T1-b)** one `performance` provenance doc per published asset; correct `(asset_id, campaign_id, event_id)` linkage; `channels` match `product_route` (poster/tshirt → shopify+printful; social_only → social); `metrics=None`; `metrics_status="pending_sync"`; `window_days=7`.
- **(T1-c)** idempotency — a second `record_outcomes` call upserts (does not duplicate) the rows.
- **(T1-d)** no-op guard — `record_outcomes` on an event with no published assets writes nothing and returns `nothing_to_record`.
- **(T1-e)** terminal text is honest — reports tracking/pending; does **not** assert sales/engagement numbers.
- Single run authoritative (deterministic). The CI ship gate.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_8_trace.py -v`

---

## T-8.10: Full verification + merge

Files: (verification only) + `CLAUDE.md` (merge-commit "Next action" update)
Acceptance — all green:
- Models: `.venv/bin/python -m pytest tests/test_models.py -v -k "performance"`
- Write wrapper: `.venv/bin/python -m pytest tests/test_step_8.py -v -k "record_performance or channels"`
- Spine regression: `.venv/bin/python -m pytest tests/test_step_8.py -v -k "baseline or pending_neutral"`
- Capability: `.venv/bin/python -m pytest tests/test_step_8.py -v -k "record_outcomes"`
- Full unit suite (no regression, incl. Step 2): `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals`
- Import check: `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"`
- Tier-1 gate: `.venv/bin/python -m pytest tests/evals/test_step_8_trace.py -v`
- **Consult advisor before declaring done** (per workflow.md Phase 6) — independent read on plan→code fidelity, that the eval exercises what it claims, and that nothing was quietly cut.
- Commit on `step/8-outcomes`; update `CLAUDE.md` § Current Phase "Next action" (Step 8 merged; capabilities 1–9 complete; next is the back-third delivery roadmap — see `project_delivery_roadmap_todo`); merge to `main` (fast-forward).

Verify: all commands above pass; `main` is green; the 9-capability arc is complete.

Known deviations from plan:
- **`published_urls` added to `Asset` model** — `get_assets_for_event` is the first code to read a published asset back through `Asset.model_validate`; Step 7's `record_execution_result` writes `published_urls` to the asset doc which `extra="forbid"` would reject. Added `published_urls: dict | None = None` to `Asset`. Not a `docs/specs/` change; no D-entry needed.
- **T1-a/T1-e eval framing** — "(T1-a) coordinator calls `record_outcomes` once" and "(T1-e) honest terminal text" are enforced by the prompt edit + no-op guard; the eval verifies the return-dict shape and written-doc shape (the correct proxy for a no-LLM capability). Live coordinator behaviour is deferred like T-7.15.

---

## Task dependency summary

```text
T-8.0 (housekeeping, doc-only)
   │
   ▼
T-8.1 (models) ─→ T-8.2 (conftest helper)
   │
   ▼
T-8.3 (record_performance + channels_for_route)
   │
   ├─→ T-8.4 (spine fix + pending-neutral regression)   [independent of T-8.5; can parallel]
   │
   ▼
T-8.5 (record_outcomes capability + no-op guard)
   │
   ▼
T-8.6 (register tool) ─→ T-8.7 (coordinator prompt)
   │
   ▼
T-8.8 (eval conftest) ─→ T-8.9 (Tier-1 trace eval)
   │
   ▼
T-8.10 (full verification + advisor + merge)
```

The spine fix (T-8.4) is the only genuinely new engineering; everything else is small and pattern-following (a model, an idempotent wrapper, a no-LLM capability, a tool registration, a prompt edit, an eval extension).
