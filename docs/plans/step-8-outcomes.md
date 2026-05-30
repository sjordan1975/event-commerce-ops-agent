# Step 8 — `record_outcomes`: Implementation Plan

## Context

Step 8 delivers capability **9 of 9** — `record_outcomes` — the final capability and the close of the feedback loop. Step 7 left the executed set as published `assets` (`status="published"`, `published_urls`) and executed `campaigns` (`status="executed"`, `execution`). Step 8 writes one **provenance record** per published asset into the `performance` collection: true linkage (`asset_id` / `campaign_id` / `event_id`), the channels awaiting measurement, the 7-day window anchor, and **metrics left null/pending**. It is the second coordinator-plane step after Step 7 and, like Step 7, **adds zero workflow nodes** (`build_pipeline_graph()` stays at 9).

Prerequisite: Step 7 (`execute_approved_campaigns` + HITL) merged to `main`. The graph is unchanged.

---

## THE decision the human gate must explicitly bless: thin honest coda (Hard Constraint #1)

**This is the load-bearing decision of the step, and it touches Hard Constraint #1 ("do not remove capabilities"). It must be blessed at the human gate, not waved through.** Source: `docs/_step-8-notes.md` § "Working direction (decided 2026-05-29)" + § "Design fork — RESOLVED", which the user pointed at directly (endorsing the direction). This plan formalizes it; the D-entry (D-032) records it.

**`record_outcomes` is descoped to a thin, honest coda that does not fabricate performance data.** The coda writes a **provenance record only** — true linkage, `window_start` (= publish time), `window_days: 7`, `recorded_at`, **`metrics: null`**, `metrics_status: "pending_sync"`. It records that the event's outcomes are *tracked and awaiting an external sync* without inventing a sale.

Why this is **descope, not removal** (the Hard Constraint #1 framing):

- **Capability 9 still exists** and runs end-to-end (read published assets → write performance rows → terminal report). The agent-facing tool, the DB write, the eval, the demo beat are all built.
- **The rich version is the named enterprise path:** real engagement/conversion ingested **asynchronously** via Shopify order webhooks / channel analytics over the 7-day window, populating the `metrics` nulls and flipping `metrics_status` to `synced`. That is out-of-band infrastructure (no live order webhook in the demo), not agent logic.
- **The coda's job is a *demonstrated* seam.** "Synced by another process" reads as hand-waving unless shown. The coda writes the exact row the sync would populate, and the demo points at it: *"the seam is here; external sync lands in this record."* This is why we go **thin, not zero** — full removal would delete the very artifact that makes the reframe credible, saving almost nothing.

**Why null, not zero.** `metrics: null` = "not yet measured." `metrics: {orders: 0}` = a measured claim that nothing sold — a fabrication 20 minutes after kickoff. Null is the honest value; the `metrics_status` discriminator is the explicit "pending" marker the sync process keys on.

> **Supersession note (reconcile before implementing):** `_step-8-notes.md` § "Honesty caveats" item 1 still says *"`record_outcomes` writes synthetic metrics"* and cites `01-requirements.md`. That is the **older framing**; the dated § "Design fork — RESOLVED" supersedes it to **provenance / no-fabrication**. `01-requirements.md`:261 carries the same stale "synthetic values" language and is **corrected in D-032** (§ Branch housekeeping). Where the two conflict, the resolved no-fabrication direction wins.

### Protect the Step-2 commercial spine from this step's own writes (load-bearing)

The notes are emphatic that the cut must not creep into `build_event_context`'s baseline read. There is a non-obvious self-inflicted way it could: **the pending-sync provenance docs land in the same `performance` collection that the Step-2 baseline aggregates read.**

`aggregate_performance_for_events` (`src/db/performance.py`:14, called by `build_event_context` at `context.py`:81) runs `$match {event_id ∈ …}` → `$lookup` to assets → `$group` by `product_route` with `total_orders: {$sum: "$metrics.shopify.orders"}` **and `count: {$sum: 1}`**. A null-metric provenance doc contributes **0 orders but +1 to `count`/`asset_count`** — i.e. it registers as a zero-performer and dilutes any per-route ranking or ratio the baseline implies.

**Mitigation (the discriminator must be honored by the reader, not just stamped by the writer):** add a leading `{"$match": {"metrics_status": {"$ne": "pending_sync"}}}` to `aggregate_performance_for_events`'s pipeline so the baseline aggregates only *measured* performance (seeded data + future synced rows), never pending provenance. Accompanied by a regression test asserting the baseline is **pending-neutral** (identical output with and without pending docs present).

This is demo-moot (Event 1 `upset_victory` vs Event 2 `draw` are different `outcome_type`s — no cross-read), but it is a latent distortion of the exact spine the notes protect, and it is a one-line `$match` now vs. a confusing baseline bug to chase later. **In scope this step.**

---

## What carries N→N+1, and what this step honestly claims

Only **one** channel carries forward and it is **append-only**: the consequence of a run (outcomes) attaches to the `assets`/`performance` corpus. Unchanged facts (team, `outcome_type`) are re-supplied each run by the operator; independent facts (`player_context`) are static seed Step 8 never touches.

**Step 8's honest, narrow claim:** "the corpus of known-performance exemplars grows, so similarity-grounded exploitation gets better-grounded over time, without retraining." **Not** "the agent rebuilds understanding each run." And note (correcting an earlier loose claim, per the notes): performance is consumed via **Step 2's `historical_baseline`** off *seeded* data — **not** via the Step-3 vector search (which projects `asset_id, event_id, product_route, scores, similarity`, never metrics). Performance-weighted similarity re-ranking is enterprise-path. So even the "improves over time" story routes through the Step-2 baseline, which is exactly why the spine-protection `$match` above matters.

---

## Why this is *not* a post-approval mini-Workflow (resolves the Step-7 flag)

The Step-7 plan explicitly deferred this question to Step 8: *"if `record_outcomes` lands deterministic, reconsider folding execute + record into a small post-approval workflow"* (D-031(h)). **Resolution: keep `execute_approved_campaigns` and `record_outcomes` as sibling coordinator `FunctionTool`s, prompt-ordered. Do not build a post-approval `Workflow`.** The argument:

- `execute_approved_campaigns` **already ships as a coordinator `FunctionTool`** (`src/agent.py`:292, D-031(a)) — it lives coordinator-side for HITL-adjacency reasons. The deterministic `execute → record` tail sits **downstream of the irreducibly coordinator-plane branch** (redraft-loop vs. execute, conditional on operator input).
- Graph-wiring the tail would require pulling `execute` **back out of the coordinator plane into a node**, reopening D-031(a) — to gain a 2-node graph whose second node is a trivial provenance insert. That cost (re-litigating where execution lives) buys no branching, no strategic node, no reuse. It is the wrong trade.
- **D-023 tension is real and acknowledged:** the `execute → record` order is *prompt-enforced*, not graph-enforced, and D-023 says deterministic order should be graph-wired. We mitigate it the same way Step 7 mitigated the redraft cap — **defense in depth, not prompt-alone**: the coordinator prompt's post-approval protocol gets the ordering rule (first-class, already exists), **and** `record_outcomes` carries a **tool-level no-op guard** — if no published-but-unrecorded assets exist for the event, it returns `{"status": "nothing_to_record"}` instead of writing. The guard is robust to LLM mis-ordering (it keys on actual DB state, not prompt compliance): calling `record_outcomes` before `execute` simply finds nothing and no-ops.

This is the honest answer to D-031(h)'s "revisit at Step 8": revisited, declined, with reasons — not "buys nothing."

---

## The capability surface

### Coordinator tool (the agent-facing surface)

| Surface | Type | Notes |
| --- | --- | --- |
| `record_outcomes(event_id)` | `FunctionTool` (new) | Reads published assets for the event, writes one provenance `performance` doc per asset (metrics pending), returns a summary. **No LLM call. No external API call.** Tool-level no-op guard if nothing to record. |

`request_human_approval`, `apply_approval_decisions`, `redraft_campaigns`, `execute_approved_campaigns`, `run_event_pipeline`, and the clarification sub-agent are all unchanged. `record_outcomes` is the **first purely-computational coordinator capability** — no Gemini call anywhere in its path.

### Internal Python pieces (none agent-facing)

| Piece | File | Purpose |
| --- | --- | --- |
| `record_performance(asset_id, campaign_id, event_id, product_route, window_start, metrics=None)` | `src/db/performance.py` (extend) | Upserts one provenance doc keyed by `(asset_id, event_id)`. Derives `channels` from `product_route`. `metrics=None`, `metrics_status="pending_sync"`. **Idempotent.** |
| `get_outcome_inputs(event_id)` | reuse — **no new reader** | `get_assets_for_event(event_id, status="published")` (exists, `assets.py`:26) joined with `get_campaigns_by_ids([…])` (exists, `campaigns.py`:153) for `execution.executed_at` (the window anchor). |
| spine fix in `aggregate_performance_for_events` | `src/db/performance.py` (modify) | Leading `$match` excluding `metrics_status == "pending_sync"` so pending docs never dilute the Step-2 baseline. |
| `record_outcomes(event_id, tool_context)` | `src/capabilities/outcomes.py` (new) | The capability: read published assets → per asset build + write provenance row → return summary. No-op guard. |

Per D-019, `MongoMCPClient` stays the only programmatic client. `record_outcomes` is registered in `build_coordinator()` alongside the other coordinator `FunctionTool`s.

---

## What the LLM does

**Nothing.** `record_outcomes` is bounded computation end-to-end: read persisted state, write provenance rows, report. There is no judgment, no narrative, no `response_schema`. This is the cleanest "the toolbelt runs out after `record_outcomes`" exit (`agentic-model.md`:110). The only LLM involvement is the **coordinator** deciding *to call* `record_outcomes` after `execute` (a prompt-ordered dispatch, not reasoning inside the capability).

---

## What the capability does internally

```text
record_outcomes(event_id, tool_context)                      # FunctionTool, post-execute
    published = await get_assets_for_event(event_id, status="published")
    if not published:
        return {"status": "nothing_to_record", "event_id": event_id}   # no-op guard
    campaigns = await get_campaigns_by_ids([a.campaign_id for a in published])
    by_id = {c.campaign_id: c for c in campaigns}
    recorded = []
    for a in published:
        c = by_id.get(a.campaign_id)
        window_start = (c.execution or {}).get("executed_at") if c else None
        await record_performance(
            asset_id=a.asset_id, campaign_id=a.campaign_id, event_id=event_id,
            product_route=a.product_route, window_start=window_start, metrics=None,
        )
        recorded.append({"asset_id": a.asset_id, "campaign_id": a.campaign_id,
                         "channels": channels_for_route(a.product_route)})
    return {"status": "recorded", "event_id": event_id,
            "count": len(recorded), "pending_sync": True, "records": recorded}
```

`channels_for_route`: `poster`/`tshirt` → `["shopify", "printful"]`; `social_only`/`None` → `["social"]` (same `product_route` channel map as Step 7 execution, D-030).

`record_performance` (the upsert):

```text
record_performance(asset_id, campaign_id, event_id, product_route, window_start, metrics=None)
    doc = Performance(
        performance_id = deterministic(asset_id, event_id),   # stable upsert key
        asset_id, campaign_id, event_id, product_route,
        channels = channels_for_route(product_route),
        metrics = metrics,                                     # None in the coda
        metrics_status = "synced" if metrics else "pending_sync",
        window_days = 7, window_start = window_start,
        recorded_at = now_iso(),
    )
    await client.call("update-many", {                        # upsert → idempotent
        filter: {asset_id, event_id}, update: {"$set": doc}, upsert: True })
```

**Window anchor:** `window_start` = the campaign's `execution.executed_at` (true publish time; spec: "rolling 7 days *from `published_at`*", `01-requirements.md`:62). `recorded_at` = now. If `execution.executed_at` is somehow absent (defensive), fall back to `recorded_at`.

**Idempotency:** upsert by `(asset_id, event_id)` rather than the inventoried `insert-many`. Execution is *retriable* (Step 7) — a re-run of `execute` then `record_outcomes` must not double-write. **This is a deviation from `db-wrapper-inventory.md`'s `insert-many`** and is recorded in D-032.

---

## Pydantic models (new)

```python
# The future measured shape — channel-broken, all-Optional. The coda writes metrics=None;
# the external sync (enterprise path) populates this and flips metrics_status to "synced".
class PerformanceMetrics(BaseModel):
    shopify: dict | None = None      # {views, orders, revenue_usd}
    printful: dict | None = None     # {units_fulfilled}
    social: dict | None = None       # {impressions, saves}

# The persisted provenance document.
class Performance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    performance_id: str
    asset_id: str
    campaign_id: str
    event_id: str
    product_route: str | None
    channels: list[str]                                  # channels awaiting sync, from route
    metrics: PerformanceMetrics | None = None            # null until external sync
    metrics_status: Literal["pending_sync", "synced"] = "pending_sync"
    window_days: int = 7
    window_start: str | None                             # publish time (campaign.execution.executed_at)
    recorded_at: str
```

`Performance` carries `extra="forbid"` (persisted document discipline, matching `Event`/`Asset`/`Campaign`/`Approval`). `PerformanceMetrics` is the future shape — defined now so the seam is typed, written as `None` by the coda. Neither is fed to an LLM as a `response_schema`, so the Steps-2/4/5/6 `additionalProperties` carve-out does not apply.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `PerformanceMetrics`, `Performance` | `src/models.py` (extend) | Provenance doc + future measured shape |
| 2 | `record_performance` (upsert) + `channels_for_route` helper | `src/db/performance.py` (extend) | Primary write; idempotent; channel map |
| 3 | spine fix — `metrics_status != pending_sync` `$match` | `src/db/performance.py` (modify `aggregate_performance_for_events`) | Pending docs never dilute the Step-2 baseline |
| 4 | `record_outcomes(event_id)` + no-op guard | `src/capabilities/outcomes.py` (new) | The capability |
| 5 | register `record_outcomes` | `src/agent.py:build_coordinator` | Add the coordinator `FunctionTool` |
| 6 | coordinator prompt — post-execute step | `prompts/v3/coordinator_system.md` (small edit) | After `execute`, call `record_outcomes(event_id)`; honest terminal report ("outcomes tracked, pending sync") |
| 7 | Conftest helper | `tests/conftest.py` (extend) | `build_valid_performance()` |
| 8 | Tests — unit | `tests/test_step_8.py` (new), `tests/test_models.py` (extend) | `Performance` model; `record_performance` upsert (idempotent, channel-by-route, metrics=None/pending); `record_outcomes` (one doc per published asset, no-op guard, window anchor from `execution.executed_at`); **baseline-is-pending-neutral** regression on `aggregate_performance_for_events` |
| 9 | Tests — Tier-1 trace eval | `tests/evals/test_step_8_trace.py` (new) | Deterministic, mocked: extend the Step-7 round-trip through `execute → record_outcomes`; assert provenance rows written + honest terminal text. CI ship gate |
| 10 | Eval conftest extension | `tests/evals/conftest.py` (modify) | One `(update-many, performance)` handler + one `(find, assets, status=published)` handler (clobber rule — distinct `(tool, collection)` from the existing `(aggregate, performance)`, so no collision) |

---

## Dependency order

1. **Models** — `PerformanceMetrics`, `Performance` (+ `test_models.py`).
2. **Conftest helper** — `build_valid_performance()`.
3. **`record_performance` + `channels_for_route`** — idempotent upsert, channel map. Unit-tested.
4. **Spine fix** — `aggregate_performance_for_events` `$match`; **baseline-pending-neutral** regression test. (Independent of 3; can land alongside.)
5. **`src/capabilities/outcomes.py`** — `record_outcomes` reading published assets + executed campaigns, no-op guard. Unit-tested.
6. **Register** `record_outcomes` in `build_coordinator()`; verify `build_coordinator()` imports.
7. **Coordinator prompt** — post-execute step + honest report.
8. **Tier-1 trace eval** — extend Step-7 trace through `record_outcomes`.

---

## Tool docstring (load-bearing — the coordinator reads it at call time)

```text
record_outcomes(event_id: str) -> dict

Record post-execution outcomes for an event. Call this ONCE after
execute_approved_campaigns has published the approved campaigns. Writes one
performance-tracking record per published asset, linking it to its campaign and
opening the 7-day measurement window. Engagement and conversion metrics are NOT
populated here — they are synced later by an external process; this records that
each published asset is now tracked and pending that sync. If nothing has been
published for the event, it records nothing and reports so. Makes no external
API call. After this returns, report to the operator and stop.
```

The docstring states the **post-execute precondition**, the **no-fabrication truth** (metrics pending, not written here), the **no-op behavior**, and the **terminal-after** cue — the four things the coordinator must get right.

---

## Coordinator prompt: the post-execute step (small edit)

`prompts/v3/coordinator_system.md` § "What you do" step 8 ("Report") and the post-approval protocol gain one ordered step. Current step 8 says *"After execution… stop."* New:

```text
8. Record outcomes. After execute_approved_campaigns returns, call
   record_outcomes(event_id) exactly once. This opens the performance-tracking
   record for each published asset (metrics are synced later, not now).
9. Report. Say briefly: how many items published, how many rejected, any
   failures, and that outcomes are now tracked and pending performance sync.
   Then stop. Do NOT claim sales or engagement numbers — none exist yet.
```

The "do not claim sales numbers" line keeps the terminal text honest to the coda (correcting `agentic-model.md`:103's "metrics recorded" example, which predates the thin-coda decision — note, not edit, this step).

---

## Evaluation

Step 8 is coordinator-level like Step 7, but **far thinner** — no branch, no loop, no LLM call inside the capability. One deterministic Tier-1 trace eval is the gate; no separate behavioral repetition probe is warranted (there is no protocol-order risk beyond "call record after execute," which the no-op guard already backstops and the Step-7 protocol probe's tail covers).

### Tier 1 — plumbing gate (deterministic, mocked, the merge gate)

`tests/evals/test_step_8_trace.py`. Extends the Step-7 mocked round-trip (dispatch → suspend → resume → apply → execute) through `record_outcomes`. Asserts:

- (T1-a) after `execute_approved_campaigns`, the coordinator calls `record_outcomes(event_id)` exactly once.
- (T1-b) one `performance` provenance doc per published asset, correct `(asset_id, campaign_id, event_id)` linkage, `channels` matching `product_route` (poster/tshirt → shopify+printful; social_only → social), `metrics=None`, `metrics_status="pending_sync"`, `window_days=7`.
- (T1-c) idempotency — a second `record_outcomes` call upserts (does not duplicate) the rows.
- (T1-d) no-op guard — `record_outcomes` on an event with no published assets writes nothing and returns `nothing_to_record`.
- (T1-e) terminal text is honest — reports tracking/pending, does **not** assert sales/engagement numbers.

Deterministic → single run authoritative. Zero live calls.

### Unit-level spine regression (separate from the trace eval, load-bearing)

`tests/test_step_8.py`: `aggregate_performance_for_events` returns identical output whether or not `pending_sync` docs are present in the collection — proving the Step-2 baseline is pending-neutral.

Step 8 exercises failure categories **2** (tool sequencing — record after execute; backstopped by the no-op guard) and **5** (end-state — provenance rows + honest terminal text). Not category 6 (strategy — Step 5's alone).

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v -k "performance"` | `Performance` validates + rejects extras; `PerformanceMetrics` optional-channel round-trip. |
| Write wrapper | `.venv/bin/python -m pytest tests/test_step_8.py -v -k "record_performance or channels"` | Idempotent upsert (key `(asset_id, event_id)`); channels by route; `metrics=None`/`pending_sync`. |
| Spine regression | `.venv/bin/python -m pytest tests/test_step_8.py -v -k "baseline or pending_neutral"` | `aggregate_performance_for_events` identical with/without pending docs. |
| Capability | `.venv/bin/python -m pytest tests/test_step_8.py -v -k "record_outcomes"` | One doc per published asset; window anchor from `execution.executed_at`; no-op guard on empty. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–8 unit tests green; **no Step-2 regression** (baseline read unchanged for measured data). |
| Import check | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Coordinator builds with `record_outcomes`; graph unchanged (still 9 nodes). |
| **Tier 1 — outcomes gate (deterministic, mocked, CI)** | `.venv/bin/python -m pytest tests/evals/test_step_8_trace.py -v` | (T1-a)–(T1-e). Zero live calls; single run authoritative. |

---

## Risks

| Risk | Mitigation |
| --- | --- |
| **Pending docs dilute the Step-2 baseline** (the spine the notes protect) | Reader honors the writer's discriminator: `$match metrics_status != pending_sync` in `aggregate_performance_for_events` + a pending-neutral regression test. In scope this step. |
| **Fabricating performance data** (against the decided direction) | `metrics=None`, `metrics_status="pending_sync"`; terminal text forbids claiming numbers. The honest seam, not invented sales. |
| **Coordinator skips/mis-orders `record_outcomes`** | Prompt step 8 (ordered) + tool-level no-op guard (keys on DB state, robust to mis-ordering; calling before execute finds nothing and no-ops). Defense in depth, mirroring Step 7's cap. |
| **Double-writing on execute retry** | Idempotent upsert by `(asset_id, event_id)`. Deviation from inventoried `insert-many` recorded in D-032. |
| **Stale "synthetic metrics" framing** in `01-requirements.md`/notes/agentic-model | Superseded by the resolved no-fabrication direction; `01-requirements.md`:261 corrected in D-032; agentic-model:103 example flagged (not edited) this step. |
| **Treating execute+record as a post-approval Workflow** | Declined with reasons (§ Why this is not a mini-Workflow): would reopen D-031(a), buys no branch/reuse; D-023 tension mitigated by prompt + no-op guard. |
| **Hard Constraint #1 ("don't remove capabilities")** | Framed as descope-to-coda + named enterprise sync, **not** removal — capability 9 runs end-to-end. The decision the human gate must explicitly bless (§ THE decision). |

---

## Env vars

None new. `record_outcomes` makes no LLM call and no external API call.

---

## Output consumed by

- **Future runs via `build_event_context` (Step 2)** — but **only once the external sync populates `metrics` and flips `metrics_status` to `synced`**. Until then the pending provenance rows are deliberately excluded from the baseline (the spine fix). In the MVP demo, Step 2 reads *seeded* measured performance; the rows Step 8 writes are the *demonstrated seam* for where real outcomes will land, not a live input to the same demo.
- **The demo closing beat** — the populated `performance` collection (provenance rows linking published assets → tracked outcomes) is the visible "the loop is wired and closed" artifact. Per the notes, the *money shot* is the executed artifacts (Shopify draft, Printful `mockup_url`, queued social) from Step 7 + demo-prep live wiring — Step 8 is the honest coda that shows the feedback channel exists, not the headline.
- **The agent's terminal exit** (`agentic-model.md`:110) — the toolbelt runs out after `record_outcomes`; the coordinator reports and stops. End of the 9-capability arc.

---

## Out of scope (designed-not-built)

- **`get_top_performers_by_channel(channel, since, limit)`** — the inventoried analytics aggregate (`performance aggregate` + `assets find`). "Not on the runtime path; optional for MVP." Deferred: it is demo-storytelling polish, and the thin-coda direction makes "look, the system has rich performance data" a claim we deliberately don't make this step. Bolts on later with zero retrofit cost (a read-only analytics tool). **Flag for the gate** — build a minimal version only if the demo specifically needs a "top performers" view.
- **External performance sync** — Shopify order webhooks / channel analytics ingestion populating the `metrics` nulls over the 7-day window. The named enterprise path; the coda writes the row it fills.
- **Performance-weighted similarity re-ranking** (Step 3/5) — enterprise path; the Step-3 vector search never reads metrics (notes § Honesty caveats item 2).

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

Doc-only; per CLAUDE.md every `docs/specs/` change needs a `tracking.md` D-entry.

1. **New D-entry (D-032): `record_outcomes` thin honest coda.** Captures: (a) **descope-to-coda, not removal** — capability 9 writes a provenance record (linkage + window + `metrics: null` + `metrics_status: "pending_sync"`); no fabricated performance; the rich version is the named external-sync enterprise path (frame vs. Hard Constraint #1); (b) **spine protection** — pending docs excluded from `aggregate_performance_for_events` so the Step-2 baseline stays measured-only; (c) **execute+record are sibling coordinator `FunctionTool`s, not a post-approval Workflow** (resolves D-031(h)) — declining would reopen D-031(a); D-023 order-tension mitigated by prompt + tool-level no-op guard; (d) **idempotent upsert** by `(asset_id, event_id)` — deviation from the inventoried `insert-many`; (e) **no LLM call** — first purely-computational coordinator capability; (f) supersedes the "synthetic metrics" framing in `01-requirements.md`:261 / notes / `agentic-model.md`:103. Refines D-031 (coordinator-plane capabilities), D-022 (consumers re-read persisted state), D-016/D-021 (Step-2 baseline is the live performance-consumption path).
2. **`docs/specs/01-requirements.md`:261** — correct capability 9's description: provenance/pending, **not** "written simultaneously as synthetic values." Confirm the 7-day window is the *measurement* window the external sync fills.
3. **`docs/specs/02-architecture.md`** — annotate the `performance` schema (`146-168`): MVP writes `metrics: null` + `metrics_status`; the zeroed example is the *measured* shape the sync populates. Fix the `record_outcomes` MCP block (`311-315`): `performance` upsert (not `insert-many`); the `assets.aggregate` "find best performers" line is the deferred `get_top_performers_by_channel` (not built this step).
4. **`docs/db-wrapper-inventory.md`:229-236** — update `record_performance` signature (adds `product_route`, `window_start`; `metrics` defaults `None`; upsert not `insert-many`); mark `get_top_performers_by_channel` deferred (designed-not-built).
5. **`CLAUDE.md`** — § Current Phase "Next action" → Step 8 plan written / tasks next; note `record_outcomes` registered as a coordinator `FunctionTool` (the second coordinator-plane step; graph still 9 nodes).

Sequence on this branch: (1) housekeeping commit (items 1–5, doc-only) → (2) plan + tasks gates → (3) implementation + Tier-1 eval → (4) merge to `main` with the updated "Next action".

---

## What changed from prior planning docs

- **Capability 9 descoped to a thin honest coda** — provenance record, **no fabricated metrics** (`_step-8-notes.md` decided direction; supersedes the "synthetic values" framing). Descope, not removal — the decision the human gate blesses.
- **The Step-2 spine is protected from this step's own writes** — pending docs excluded from the baseline aggregate; the discriminator is honored by the reader, not just stamped by the writer.
- **The Step-7 fold-question is resolved** — execute + record stay sibling coordinator tools; the post-approval Workflow is declined with reasons (would reopen D-031(a); no branch/reuse to gain).
- **First purely-computational coordinator capability** — no LLM call, no external API call; the cleanest terminal-text exit of the 9-capability arc.
- **Idempotent upsert** replaces the inventoried `insert-many` (execution is retriable) — a recorded deviation.
