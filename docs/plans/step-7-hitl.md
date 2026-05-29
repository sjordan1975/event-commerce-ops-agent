# Step 7 — `request_human_approval` + `execute_approved_campaigns`: Implementation Plan

## Context

Step 7 delivers capabilities **7 and 8** of the nine — the human-in-the-loop approval gate and campaign execution — plus the **redraft loop** deferred from Step 6 (D-030). Step 6 left every surfaced queue item as a `campaigns` draft + a `pending` `approvals` entry, with the asset at `status="campaign_draft_created"`. Step 7 is what turns those drafts into published campaigns: the operator reviews the pending batch, decides per item (`approved` / `rejected` / `edit_requested`), edited items loop back through copy regeneration, and approved items are executed across Shopify / Printful / social (stubbed at the seam this step — see § Execution scope).

This is the **first step whose capabilities live coordinator-side, not in the workflow graph** (`02-architecture.md`:389). Steps 1–6 each extended `build_pipeline_graph()` with a node. Step 7 adds **zero workflow nodes**. The pipeline already ran to `END` and produced the drafts; the coordinator `LlmAgent` picks up from there, suspends on approval, and orchestrates the post-approval branch. This inflection — capabilities leaving the graph for the conversation plane — is the architectural spine of the step and is stated explicitly so it is not mistaken for a regression to the pre-D-024 "agent plans the workflow" anti-pattern (it is not: see § Why this is layer-2, not the anti-pattern).

Prerequisite: Step 6 (`draft_campaigns_for_queue`) merged to `main`. The graph is unchanged. The coordinator already carries a **stub** `request_human_approval` `LongRunningFunctionTool` (`src/agent.py`:136) and a stub `approval_batch` arg — Step 7 fleshes it out and adds the post-approval tools alongside it.

---

## The architectural spine: how the HITL resume payload actually flows

**The source docs are wrong about this, and following them literally produces an unbuildable design.** Pin it first.

The wrapper inventory says `record_approval_decision` is *"called by `request_human_approval` on resume"* (`db-wrapper-inventory.md`:210), and the arch diagram (`02-architecture.md`:287-293) frames `request_human_approval` as doing the `approvals.updateOne` + `assets.updateOne` writes itself. **Both spikes contradict this.** From `spike/adk_hitl_test.py` and `spike/adk_workflow_hitl_spike.py` (claim 2): a `LongRunningFunctionTool` function returns `None` **once**, the runner suspends, and on resume the operator's `FunctionResponse.response` dict is delivered **to the LLM as the tool result** — the python function body **does not re-run**. There is no "on resume" inside `request_human_approval`. It cannot record decisions, because it never sees them.

The resolution — and it is the same persistence philosophy as D-022 (state lives on the document; consumers re-read from Mongo):

```text
1. Coordinator calls  request_human_approval(event_id)         ← LongRunningFunctionTool
      → reads get_pending_approvals(event_id), joins each to its campaign copy, and
        RETURNS the grouped batch as the tool's INITIAL long-running response
        ({"status":"pending","approval_batch":...}) so the surface can render it —
        then SUSPENDS pending the decisions FunctionResponse. A read + gate. No writes.
      → the batch carries approval_id per item — the key the operator's decisions use.
      → (ADK confirm: a non-None initial return still suspends — verified in T-7.10 /
        a ~10-line spike ext; fallback is return None + surface re-fetches by event_id.)

2. Operator posts a FunctionResponse carrying a per-item DECISIONS LIST:
      { "decisions": [ {approval_id, decision, reviewer_notes}, ... ] }
   → delivered to the coordinator LLM as the tool result (NOT to the function).

3. Coordinator calls  apply_approval_decisions(decisions)      ← NEW FunctionTool
      → record_approval_decision per item: persist approval status + reviewer_notes
        + decided_at; cascade campaign/asset status. THIS is where decisions hit Mongo.
      → returns { approved:[...], rejected:[...], edit_requested:[...] }.

4. Coordinator branches on that summary (resolve-then-execute, see below):
      edit_requested present → redraft_campaigns(event_id) → request_human_approval (loop, capped)
      else                   → execute_approved_campaigns(event_id)

5. execute_approved_campaigns and redraft are PURE CONSUMERS of persisted Mongo state:
      execute reads  approvals status="approved" (join campaigns)
      redraft reads  approvals status="edit_requested" (notes included)
   Neither takes the raw resume payload. Both are re-runnable from the DB.
```

Why a **separate** `apply_approval_decisions` tool rather than folding decision-recording into `execute`: a mixed batch (some approved, some rejected, some edit_requested at once) has rejected items whose status cascade has no other home, and making `execute`/`redraft` pure consumers of persisted state keeps them testable, idempotent, and resumable (D-022). This is the single most load-bearing design choice in the step; the spec corrections in § Branch housekeeping fix the two docs that mislead.

**Mechanical certainty.** The existing spikes passed a *flat single-decision* dict through `FunctionResponse.response`. Step 7 passes a *list of decisions*. This is the one genuinely new ADK-mechanics fact, and it is verified by a **Tier-1 trace-eval assertion** (the coordinator receives the list and calls `apply_approval_decisions` with all N items) — **not** a new standalone spike. If the list does not round-trip legibly, the ~15-line extension to `spike/adk_workflow_hitl_spike.py` claim 2 is the fallback, but the trace eval is the primary check.

---

## Operator-presence assumption (load-bearing, MVP-explicit)

`request_human_approval` assumes the operator is at the keyboard. The spec is explicit (`01-requirements.md`:149): *"The agent does not time out HITL waits; it holds until the operator responds."* Mechanically:

- **Suspension, not exit.** Returning `None` parks the coordinator loop (`long_running_tool_ids` emitted); it resumes only on a matching `FunctionResponse`. This is `agentic-model.md`:104's "mid-loop suspension."
- **No logical timeout.** The agent runs no wall-clock timer. It waits indefinitely for the human.
- **"No timeout" ≠ "no bound."** Orthogonal concepts, kept separate throughout this plan: the *wait* is unbounded (operator presence); the *redraft loop* is **capped** (§ Safety cap). Wait forever for a human; do not let the redraft ping-pong spin.
- **Honest boundary: process-lifetime, not eternal.** With `InMemorySessionService` (local/demo) the parked state lives in memory — a process death loses it. Durable resume across restarts needs a persistent session service (`02-architecture.md`:400, Cloud Run). For the single-session, operator-present demo, in-memory is correct; the boundary is recorded, not closed.

Enterprise path (out of MVP scope, Hard Constraint #8): unattended batched processing with no clarification/approval presence — `01-requirements.md`:153.

---

## The display batch (what the operator decides over)

`request_human_approval(event_id)` echoes a structured batch built from `get_pending_approvals(event_id)` joined to each item's campaign copy. The shape is **grouped by queue half** (exploitation vs exploration), each item carrying its agent narrative + generated copy + image reference, and **every item keyed by `approval_id`**:

```json
{
  "event_id": "wc2026-match-42",
  "exploitation": [
    {
      "approval_id": "a1", "campaign_id": "c1", "asset_id": "img_07",
      "content_url": "gs://.../img_07.jpg",
      "queue_rank": 1,
      "queue_rationale": "Messi mid-celebration, sharp — matches the top-converting upset archetype",
      "product_route": "poster",
      "headline": "Messi ends France's reign in extra-time thriller",
      "caption": "…", "hashtags": ["#WorldCup2026", "#ArgentinaVsFrance"],
      "timing_recommendation": "2026-07-14T22:00:00Z"
    }
  ],
  "exploration": [
    {
      "approval_id": "a3", "campaign_id": "c3", "asset_id": "img_31",
      "content_url": "gs://.../img_31.jpg",
      "queue_rationale": "Didn't match past winners, but the bench-celebration captures the disbelief — worth your time",
      "product_route": "social_only",
      "headline": "…", "caption": "…", "hashtags": ["…"]
    }
  ]
}
```

Three properties of this contract:

- **The grouping is presentational; the decision identity is `approval_id`.** Operator decisions come back as the flat `approval_id`-keyed list (§ spine) regardless of which half an item sat in. Grouping by queue half costs nothing mechanically — it makes the **exploration reasoning legible as its own block**, which is the demo's hero moment (`01-requirements.md`:282, 308: "visible per-item reasoning").
- **It carries `content_url`** — the operator cannot decide without seeing the photo (thumbnail in a UI; link in chat).
- **Naming:** the persisted field is `queue_type ∈ {exploitation, discovery}` (`02-architecture.md`:70); the operator-facing label is "exploration." The display maps `discovery → exploration` so it does not read as two concepts.

### Presentation surface (separate track — not Step 7 agent scope)

The display batch is the **agent-side contract**; the *surface* that renders it is front-end / demo-prep work, tracked separately. The intended caller is a **lightweight approval app** (e.g. small Next.js or Python app) that renders thumbnails + per-item reasoning and **posts the structured `FunctionResponse`** (the decisions list, matching the suspended tool-call id) directly from the operator's choices. This is not merely the more demoable option — it is the **technically cleaner** one: the HITL resume expects a structured `FunctionResponse`, which an app constructs naturally from per-item controls. Pure terminal free-text chat would require an intermediate step to parse free text ("approve 1, 2, 5; reject 3; redo 4…") into the structured list — a failure surface and awkward against the long-running-tool protocol. A polished UI is **not** required (judging-criteria's "clean approval UI" is satisfied by the lightweight version); terminal chat stays a viable fallback with the parsing caveat noted. **The Step 7 plan owns the contract; it does not own the front-end build.**

---

## Mixed-batch control flow: resolve-then-execute (canonical)

A single approval batch can return mixed decisions. The canonical post-approval flow is **resolve-then-execute**:

> Loop `redraft → request_human_approval` until **no `edit_requested` items remain** (or the cap fires), **then** make **one** `execute_approved_campaigns(event_id)` call on the final approved set.

**Approvals accumulate across cycles (non-obvious but correct).** Round-1 `approved` items go to `status="approved"` immediately and simply *wait* — they are not in round-2's pending batch (which is freshly-redrafted `pending` items only). The final `execute` reads `status="approved"` from Mongo, so it picks up **all** approvals accumulated across every cycle. Round-1 approvals are never lost in the loop; this falls out of the persisted-state design.

Rationale: one execute call = one clean trace; execute stays a pure consumer of *terminal* Mongo state; external-API calls are never interleaved with redraft cycles; and the eval asserts a single canonical order. The alternative (interleaved — execute the approved subset immediately, redraft the rest, execute those later) is also valid and naturally idempotent (`get_approved_campaigns` only pulls `status="approved", execution=None`), but it multiplies the LLM-orchestration surface the eval must hammer.

> **Operator-visible consequence (veto point):** under resolve-then-execute, approved items do **not** publish live while other items are still being edited — the whole batch executes once editing settles. If the demo needs approved items to ship mid-edit, switch to interleaved. Defaulting to resolve-then-execute.

---

## Why this is layer-2, not the anti-pattern

Step 7 puts a **stateful multi-tool protocol back on the coordinator LLM** (receive decisions → `apply` → branch → maybe loop → `execute`), on `gemini-2.5-flash`. That is the surface `agentic-model.md` § anti-pattern warns about — so state plainly why it does *not* fire here:

- `agentic-model.md`:56 lists **"when to redraft on `edit_requested`"** as a sanctioned **layer-2 composition** decision. The post-HITL branch is genuine composition over *operator input*, not a known deterministic sequence the LLM is being forced to re-derive.
- This is **not** a second strategic decision (layer 3 stays `propose_review_queue` alone) and **not** a workflow the LLM is re-planning (the deterministic pipeline is still graph-wired and ran to `END`).
- The memory rule "deterministic steps should be graph-wired, not LLM-chosen" (D-023) does **not** apply: the *branch* is conditional on a human decision (irreducibly runtime), and the *mechanics* under each branch (`execute`, `redraft`) are single iterating capabilities, not multi-node ordered graphs. A post-approval mini-`Workflow` is **rejected** as over-engineering — revisit only when `record_outcomes` (Step 8) gives two ordered deterministic post-approval steps.

Because the prompt now carries this protocol, **`coordinator_system.md` is a first-class component this step** (its own component row + risk row + eval assertions), not Step 6's one-liner.

---

## The capability surface

### Coordinator tools (the agent-facing surface — all coordinator-side)

| Surface | Type | Notes |
| --- | --- | --- |
| `request_human_approval(event_id)` | `LongRunningFunctionTool` (exists, stub → fleshed) | Read `get_pending_approvals(event_id)`, join campaign copy for display, echo the batch (carrying `approval_id` per item), return `None` to suspend. **No decision writes.** `tool_context.actions.skip_summarization = True`. Signature changes from the stub's `approval_batch` to `event_id` — the batch is built from persisted state, not passed in (the stub's `drafts`-derived batch carries no `approval_id` to key decisions against). |
| `apply_approval_decisions(decisions)` | `FunctionTool` (new) | Persists each operator decision via `record_approval_decision`; returns `{approved, rejected, edit_requested}`. The only place decisions hit Mongo. |
| `redraft_campaigns(event_id)` | `FunctionTool` (new) | Thin shim: `await draft_campaigns_for_queue(event_id, operator_notes=None)` in **redraft mode** (reads persisted `edit_requested` approvals). Increments + checks the redraft cap. |
| `execute_approved_campaigns(event_id)` | `FunctionTool` (new) | Pure consumer of `approvals status="approved"`; per-item channel dispatch + status machine. |

`run_event_pipeline` and the clarification sub-agent are unchanged. `record_outcomes` (capability 9) is Step 8.

### Internal Python pieces (none agent-facing)

| Piece | File | Purpose |
| --- | --- | --- |
| `record_approval_decision(approval_id, decision)` | `src/db/approvals.py` (new) | Bundled write: `approvals` update (`status`, `reviewer_notes`, `decided_at`) + cascade — `campaigns` status (`approved`/`rejected`; stays `draft` for `edit_requested`) + `assets` status (`rejected` on reject; else unchanged). |
| `get_pending_approvals(event_id, limit=50)` | `src/db/approvals.py` (new) | `approvals find {event_id, status:"pending"}`. **Event-scoped** so a second batch can't bleed in. |
| `reset_approval_to_pending(approval_id)` | `src/db/approvals.py` (new) | Redraft: `approvals` → `status:"pending"`, clear `reviewer_notes` (consumed), `decided_at:None`. |
| `get_approved_campaigns(event_id, limit=50)` | `src/db/campaigns.py` (extend) | `approvals find {event_id, status:"approved"}` joined with `campaigns find`; filters `execution=None`. Returns `list[ApprovedCampaign]`. Event-scoped. |
| `get_edit_requested_campaigns(event_id)` | `src/db/campaigns.py` (extend) | `approvals find {event_id, status:"edit_requested"}` joined with `campaigns`. Redraft input (notes included). |
| `overwrite_campaign_draft(campaign)` | `src/db/campaigns.py` (extend) | Redraft: `campaigns update-many` replacing `generated_copy` + bump `created_at`; asset stays `campaign_draft_created`. |
| `mark_asset_executing(asset_id)` | `src/db/assets.py` (extend) | `assets` → `status:"executing"`. Pre-external-call transition; visible in trace. |
| `record_execution_result(asset_id, campaign_id, result)` | `src/db/campaigns.py` (extend) | Bundled: `assets` → `status:"published"` + `published_urls`; `campaigns` → `status:"executed"` + `execution`. |
| `record_execution_failure(asset_id, campaign_id, error)` | `src/db/campaigns.py` (extend) | Failure path: `assets`/`campaigns` → status reflecting failure + error detail. |
| `_shopify_create_product`, `_printful_create_mockup`, `_printful_poll_mockup`, `_simulate_social_post` | `src/capabilities/execution.py` (new) | **Mock seams** (§ Execution scope). Stubbed bodies returning realistic canned payloads this step; the eval-mock + demo-prep-live seam. |
| `execute_approved_campaigns(event_id)` | `src/capabilities/execution.py` (new) | The capability: fetch approved → per item `mark_asset_executing` → channel dispatch by `product_route` → `record_execution_result` (or `_failure`). |
| redraft branch | `src/capabilities/drafts.py` (extend) | `draft_campaigns_for_queue` gains its **redraft mode** (D-030): reads `edit_requested` campaigns, regenerates copy with notes, `overwrite_campaign_draft`, `reset_approval_to_pending`. |

Per D-019, `MongoMCPClient` stays the only programmatic client. `request_human_approval`, `apply_approval_decisions`, `execute_approved_campaigns` are coordinator `FunctionTool`s registered in `build_coordinator()` — they are the first capabilities registered as agent tools rather than graph nodes (consistent with `run_event_pipeline` being a tool, not a node).

---

## Redraft: a state-consumer, identical in shape to execute (kills the `operator_notes` muddiness)

`apply_approval_decisions` persists `reviewer_notes` onto each `edit_requested` approval doc. Therefore **redraft reads the notes from Mongo** — it is a pure consumer of persisted `status="edit_requested"` state, exactly like `execute` consumes `status="approved"`. Consequence, stated crisply so it does not wobble:

- **Production redraft path ignores `operator_notes`** and reads `get_edit_requested_campaigns(event_id)` (notes included).
- The `operator_notes: dict | None = None` parameter on `draft_campaigns_for_queue` (reserved in Step 6, D-030) **stays only for signature stability + unit-test injection**. It is not on the production path.
- Redraft fetch differs from first-pass (D-030 flagged this): first-pass reads `status="scored"` + `queue_type`; redraft reads `edit_requested` approvals already at `campaign_draft_created`. The redraft branch is effectively its own internal function, not a thin conditional on the first-pass loop.

Redraft regenerates copy by reusing `_draft_copy_for_asset` with the reviewer notes injected into `item_context` (the prompt already carries an asset-context block; notes append as an "operator revision request" line). Then `overwrite_campaign_draft` + `reset_approval_to_pending`, leaving the item ready for another `request_human_approval` pass.

---

## Status machine (Step 7 is the writer for everything past `campaign_draft_created`)

```text
asset.status:    campaign_draft_created ──approved──▶ (held) ──execute──▶ executing ──▶ published
                                        ──rejected──▶ rejected
                                        ──edit_requested──▶ campaign_draft_created (redraft, unchanged)
campaign.status: draft ──approved──▶ approved ──execute──▶ executed
                       ──rejected──▶ rejected
                       ──edit_requested──▶ draft (overwritten on redraft)
approval.status: pending ──▶ approved | rejected | edit_requested
                 edit_requested ──redraft──▶ pending (notes cleared, decided_at reset)
```

**Execution failure is retriable, not terminal (MVP).** `record_execution_failure` leaves `campaign.execution = None` and the `approval` at `status="approved"`, so a re-run of `execute_approved_campaigns(event_id)` re-picks the item (`get_approved_campaigns` filters `execution=None`). The asset reverts from `executing` rather than landing in a terminal `failed` state. A terminal failed state with operator escalation is enterprise-path. Mostly moot while helpers are stubbed-to-succeed, but pinned so the retry behavior is by-design, not accidental.

No `Asset`/`Campaign`/`Approval` model field changes are needed — `status`, `published_urls`, `execution`, `reviewer_notes`, `decided_at` all already exist (Step 6 / pre-existing schemas). Step 7 is their first writer for the post-approval states.

---

## Pydantic models (new)

```python
# Input model — parsed from the operator's FunctionResponse payload. extra="forbid"
# to reject malformed/typo'd decisions at the boundary.
class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    decision: Literal["approved", "rejected", "edit_requested"]
    reviewer_notes: str | None = None

# Join view — get_approved_campaigns / get_edit_requested_campaigns. Not persisted.
class ApprovedCampaign(BaseModel):
    approval_id: str
    campaign: Campaign
    asset_id: str
    product_route: str | None

# Execution outcome — persisted into campaign.execution + asset.published_urls.
class ExecutionResult(BaseModel):
    shopify: dict | None = None      # {product_id, product_url}
    printful: dict | None = None     # {task_id, mockup_url}
    social: dict | None = None       # {status:"queued", queued_at}
    executed_at: str

class ExecutionError(BaseModel):
    channel: str
    message: str
    failed_at: str
```

`ApprovalDecision` carries `extra="forbid"` (boundary validation of operator input). `ApprovedCampaign`/`ExecutionResult`/`ExecutionError` are internal transfer shapes. None is fed to an LLM as a `response_schema`, so the Steps-2/4/5/6 `additionalProperties` constraint does not apply here.

---

## Safety cap (Gap 1 — in-scope THIS step, not deferred)

`safety-measures.md`:59 marks the tool-level redraft cap **"high before `request_human_approval` ships."** That is this step. Land all three:

1. **Prompt-level 3-cycle rule** — port the `prompts/v2/agent_system.md` rule (3 redraft cycles then escalate) into `prompts/v3/coordinator_system.md`. (v3 has no `agent_system.md`; the rule moves to the coordinator prompt.)
2. **Tool-level hard cap (defense-in-depth)** — `redraft_campaigns` increments a counter in `tool_context.state["redraft_cycles"]` and **refuses** past `MAX_REDRAFT_CYCLES` (env, default 3), returning a terminal "escalate to operator" result instead of redrafting. Robust to LLM mis-ordering because it counts *actual* invocations, not prompt compliance.
3. **ADK iteration cap value** — finally choose and document the explicit `Runner`/agent max-iterations value (record in `CLAUDE.md` § ADK-Specific Rules per `safety-measures.md`:93).

> The cap counter lives in **session state**, which must survive the suspend/resume park. A Tier-1 assertion proves the counter persists across a round-trip (the whole step assumes session state survives suspension — prove it once rather than assume it).

---

## Execution scope (Option 1 — stub at the seam now; live at demo prep)

Per user decision: Step 7 builds the **full execution capability** — fetch approved → per-item channel dispatch by `product_route` → status machine → result/failure persistence. The **three** Shopify/Printful helpers (`_shopify_create_product`, `_printful_create_mockup`, `_printful_poll_mockup`) have **stubbed bodies returning realistic canned payloads** (a Shopify `product_id`/`product_url`, a Printful `task_id`/`mockup_url`). `_simulate_social_post` is **not** a stub — simulation is social's *final form* (Hard Constraint #6), so it writes a real, queryable `queued` post package. The orchestration, status transitions, persistence, and route-driven channel selection are fully built and tested; only the live Shopify/Printful calls are deferred to demo-prep.

- **CI never hits live APIs** regardless — the helpers are the mock seam (analogous to `_draft_copy_for_asset`).
- **Channel selection by `product_route`** (not `platform_target` — D-030): `poster`/`tshirt` → Shopify product + Printful mockup; `social_only` (and defensive `None`) → social package only.
- **Printful polling** is an **internal async poll loop** with bounded retries + timeout inside `execute_approved_campaigns` — **not** a second `LongRunningFunctionTool` (the arch's "LongRunningFunctionTool for polling" framing, `02-architecture.md`:328, is loose; internal poll loop is the real design, per `02-architecture.md`:402). The stubbed `_printful_poll_mockup` returns `completed` immediately; the poll-loop structure is real so demo-prep only swaps the helper body.
- **Live wiring is a tracked demo-prep task** (Shopify Partners dev store + Printful free account; `SHOPIFY_*`/`PRINTFUL_TOKEN` already in `.env.template`). The `mockup_url` is "the key demo artifact" (`02-architecture.md`:126) — live eventually, just not gated on this step.
- **Social is settled** — simulated (Hard Constraint #6); `_simulate_social_post` writes the post package, no live-vs-stub distinction.

---

## What the capabilities do internally

```text
request_human_approval(event_id, tool_context)               # LongRunningFunctionTool
    tool_context.actions.skip_summarization = True
    pending = await get_pending_approvals(event_id)          # authoritative: approval_id+campaign_id+asset_id
    batch = [{approval_id, campaign_id, asset_id, headline, caption, product_route}
             for a in pending join its campaign for copy]    # display batch, keyed by approval_id
    # (echo `batch` so the operator sees it; decisions come back keyed by approval_id)
    return None                                              # suspend; NO decision writes

apply_approval_decisions(decisions, tool_context)            # FunctionTool, on resume
    approved, rejected, edited = [], [], []
    for d in decisions:                                      # each validated as ApprovalDecision
        await record_approval_decision(d.approval_id, d)     # approvals + cascade campaign/asset
        bucket the campaign_id/approval_id by d.decision
    return {"approved": approved, "rejected": rejected, "edit_requested": edited}

redraft_campaigns(event_id, tool_context)                   # FunctionTool
    n = tool_context.state.get("redraft_cycles", 0) + 1
    if n > MAX_REDRAFT_CYCLES:
        return {"status": "cap_reached", "message": "escalate to operator; revision limit hit"}
    tool_context.state["redraft_cycles"] = n
    return await draft_campaigns_for_queue(event_id)         # redraft mode (reads edit_requested)

execute_approved_campaigns(event_id, tool_context)          # FunctionTool, resolve-then-execute
    approved = await get_approved_campaigns(event_id)        # status=approved, execution=None
    results = []
    for ac in approved:
        await mark_asset_executing(ac.asset_id)
        try:
            result = dispatch_by_route(ac)                   # shopify+printful | social (stubbed helpers)
            await record_execution_result(ac.asset_id, ac.campaign.campaign_id, result)
            results.append(success)
        except ExecutionFailure as e:
            await record_execution_failure(ac.asset_id, ac.campaign.campaign_id, e)
            results.append(failure)
    return {"event_id": event_id, "executed": [...], "failed": [...]}
```

`draft_campaigns_for_queue` redraft mode (extends Step 6's function):

```text
draft_campaigns_for_queue(event_id, operator_notes=None)
    if there are edit_requested approvals for event_id:          # REDRAFT MODE (state-driven)
        for ac in await get_edit_requested_campaigns(event_id):
            item_context = {... , "operator_revision": ac.approval.reviewer_notes}
            copy = await _draft_copy_for_asset(narrative_context, item_context)
            await overwrite_campaign_draft(campaign_with_new_copy)
            await reset_approval_to_pending(ac.approval_id)      # clears notes, decided_at
        return {drafts ...}
    else:                                                        # FIRST-PASS (Step 6, unchanged)
        ... existing scored+queue_type path ...
```

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `ApprovalDecision`, `ApprovedCampaign`, `ExecutionResult`, `ExecutionError` | `src/models.py` (extension) | Input + transfer models |
| 2 | `src/db/approvals.py` | new | `get_pending_approvals`, `record_approval_decision`, `reset_approval_to_pending` |
| 3 | `src/db/campaigns.py` (extend) | mod | `get_approved_campaigns`, `get_edit_requested_campaigns`, `overwrite_campaign_draft`, `record_execution_result`, `record_execution_failure` |
| 4 | `src/db/assets.py` (extend) | mod | `mark_asset_executing` |
| 5 | `request_human_approval(event_id)` (flesh stub) | `src/agent.py` | Read `get_pending_approvals`, join copy, echo `approval_id`-keyed batch, suspend; no decision writes. Signature `approval_batch` → `event_id` |
| 6 | `apply_approval_decisions` | `src/agent.py` (new tool) | Persist decisions → bucketed summary |
| 7 | `redraft_campaigns` shim + cap | `src/agent.py` (new tool) | Dispatch redraft mode; tool-level cycle cap in `tool_context.state` |
| 8 | `execute_approved_campaigns` + 3 stubbed Shopify/Printful helpers + real `_simulate_social_post` | `src/capabilities/execution.py` (new) | Capability + channel dispatch + internal Printful poll loop; social package write is real (final form) |
| 9 | redraft branch | `src/capabilities/drafts.py` (extend) | Redraft mode (state-driven; D-030) |
| 10 | register new tools | `src/agent.py:build_coordinator` | Add `apply_approval_decisions`, `redraft_campaigns`, `execute_approved_campaigns` |
| 11 | **Coordinator prompt — first-class** | `prompts/v3/coordinator_system.md` (substantial edit) | The post-approval protocol: receive decisions → `apply` → branch (resolve-then-execute) → redraft-loop (3-cycle rule) → execute. |
| 12 | ADK iteration cap + env | `src/agent.py`, `.env.template`, README | `MAX_REDRAFT_CYCLES` (default 3); explicit ADK max-iterations value |
| 13 | Conftest helpers | `tests/conftest.py` (extension) | `build_valid_approval_decision()`, `build_valid_approved_campaign()`, `build_valid_execution_result()` |
| 14 | Tests — unit | `tests/test_step_7.py` (new), `tests/test_models.py` (extension) | Models; `record_approval_decision` cascade (3 buckets); `get_approved_campaigns`/`get_edit_requested_campaigns` joins; `mark_asset_executing`; `record_execution_result`/`_failure`; `execute_approved_campaigns` route dispatch (poster/tshirt → shopify+printful, social_only → social) with stubbed helpers; redraft mode (reads edit_requested, overwrites, resets); cap refusal |
| 15 | Tests — Tier 1 plumbing eval | `tests/evals/test_step_7_trace.py` (new) | Deterministic, mocked: full coordinator HITL round-trip — suspend → resume with a **list** of decisions → `apply` → branch → execute. Asserts protocol order + cap-survives-suspend. CI ship gate |
| 16 | Tests — behavioral branch eval | `tests/evals/test_step_7_protocol.py` (new) | Repetition (≥95%/20-run posture): coordinator reliably reads N decisions → `apply` before `execute`; redraft loops back; cap stops it. Not a single-run gate |
| 17 | Eval conftest extension | `tests/evals/conftest.py` (modification) | **One combined** `approvals` (find+update) handler branching on `status`; **one combined** `campaigns` handler; scripted `FunctionResponse` decisions-list helper |

---

## Dependency order (Phase A = HITL + redraft + cap; Phase B = execution)

**Phase A — the gate, the protocol, the loop, the bound.**
1. **Models** — `ApprovalDecision` (`extra="forbid"`), `ApprovedCampaign`, `ExecutionResult`, `ExecutionError`.
2. **Conftest helpers**.
3. **`src/db/approvals.py`** — `get_pending_approvals` (event-scoped), `record_approval_decision` (cascade), `reset_approval_to_pending` (notes cleared). Unit-tested via mocked client.
4. **`src/db/campaigns.py` reads** — `get_approved_campaigns`, `get_edit_requested_campaigns` (joins). Unit-tested.
5. **`request_human_approval(event_id)`** — flesh the stub: read `get_pending_approvals(event_id)`, join campaign copy, echo the `approval_id`-keyed batch, suspend (no decision writes). Signature changes from `approval_batch` → `event_id`.
6. **`apply_approval_decisions`** — persist + bucket. Unit-tested (3 buckets, cascade correctness).
7. **Redraft branch** in `draft_campaigns_for_queue` + `overwrite_campaign_draft` + `redraft_campaigns` shim with the **tool-level cap**.
8. **Coordinator prompt** — the post-approval protocol (resolve-then-execute, 3-cycle rule). Register `apply_approval_decisions` + `redraft_campaigns`. Verify `build_coordinator()` imports.
9. **Tier-1 HITL trace eval** — suspend → resume (decisions **list**) → apply → branch → (no execute yet; assert branch + cap-survives-suspend).

**Phase B — execution behind seams.**
10. **`src/db/campaigns.py` writes + `src/db/assets.py`** — `mark_asset_executing`, `record_execution_result`, `record_execution_failure`. Unit-tested.
11. **`src/capabilities/execution.py`** — `execute_approved_campaigns` + 3 stubbed Shopify/Printful helpers + the real `_simulate_social_post` (writes the package) + internal Printful poll loop. Unit-tested (route dispatch, success + failure paths, status machine).
12. **Register `execute_approved_campaigns`**; extend the coordinator prompt's branch to call it (resolve-then-execute).
13. **Tier-1 trace eval (full)** — extend step 9 through to `execute`; assert end-state (published + execution persisted).
14. **Behavioral branch eval** — repetition over the protocol order.

---

## Coordinator prompt: the post-approval protocol (load-bearing)

`prompts/v3/coordinator_system.md` gains a dedicated section (not a one-liner). Shape:

```text
AFTER the pipeline returns drafts:
1. Call request_human_approval with the drafted batch. WAIT for the operator's decisions.
2. When decisions arrive, call apply_approval_decisions with the full per-item list —
   ALWAYS apply before doing anything else. Never execute or redraft un-applied decisions.
3. Branch on the apply result (resolve-then-execute):
   - If any items are edit_requested: call redraft_campaigns(event_id), then go back to
     step 1 (request_human_approval) for another review pass.
   - Otherwise: call execute_approved_campaigns(event_id) ONCE on the approved set.
4. Redraft limit: after 3 redraft cycles, STOP redrafting and recommend the operator
   escalate. Do not loop further. (The redraft tool also enforces this.)
5. Never publish without an explicit operator approval decision for that item.
```

The `apply-before-anything` and `redraft-then-loop / else-execute-once` rules are exactly what the behavioral eval asserts. The 3-cycle rule is the prompt half of Gap 1 (the tool enforces the other half).

---

## Evaluation

Step 7 is **coordinator-level and multi-turn** — a different eval seam from every prior step (Steps 1–6 dispatched the workflow graph; here the action is in the coordinator loop with a scripted operator `FunctionResponse`). Two evals, matching the kind of risk:

### Eval scaffolding (mock-handler discipline — confirmed memory)

The new `approvals` reads/writes and `campaigns` reads/writes go through `_MockMCPClient`. Per the **mock-handler-clobber** rule: register **one combined** `(find, approvals)` handler that branches on `status` in the filter (`pending` / `approved` / `edit_requested`), and **one combined** `(update-many, approvals)` handler — never two handlers for the same `(tool, collection)`, which silently clobber. Same for `campaigns`. Decisions are injected via a scripted `FunctionResponse` carrying the **list** payload.

### Tier 1 — plumbing gate (deterministic, mocked, the merge gate)

`tests/evals/test_step_7_trace.py`. External helpers stubbed (canned payloads), `_draft_copy_for_asset` mocked, approvals/campaigns seeded. A full coordinator round-trip: dispatch → suspend at `request_human_approval` → resume with a **decisions list** → assert:
- (T1-a) coordinator received the list and called `apply_approval_decisions` with **all N** items (the list-payload round-trip — the one new ADK fact).
- (T1-b) `apply` persisted correctly: approvals → right statuses + `reviewer_notes` + `decided_at`; cascade to campaign/asset status; **rejected** items reach `rejected`, **edit_requested** persist notes.
- (T1-c) branch correctness — an all-approved batch → exactly one `execute_approved_campaigns`; a batch with `edit_requested` → `redraft_campaigns` then back to `request_human_approval` (no execute yet).
- (T1-d) execution end-state — approved items → asset `published` + `published_urls`, campaign `executed` + `execution`; route dispatch correct (poster/tshirt → shopify+printful keys; social_only → social key).
- (T1-e) **cap survives suspend/resume** — `redraft_cycles` in session state increments across a park; the 4th redraft is refused by the tool.
- (T1-f) reasoning text present (CoT directive); `apply` always precedes `execute`/`redraft`.

Deterministic → single run authoritative. Zero live calls (no `GOOGLE_API_KEY`, no Shopify/Printful).

### Behavioral branch probe (repetition — the ≥95%/20-run posture)

`tests/evals/test_step_7_protocol.py`. The behavioral risk is the **coordinator protocol**, on flash: does it reliably (a) apply before execute, (b) redraft-then-loop on `edit_requested`, (c) execute-once otherwise, (d) stop at the cap? This is where repetition earns its keep — a protocol that passes 5/5 in CI but 17/20 manually is a flake. Run with the project's pass-rate posture; on failure, climb the remediation ladder prompt-first (the protocol section above is the first rung). Not a single-run merge gate; Tier 1 + the unit suite are.

Step 7 exercises failure categories **2** (tool sequencing — newly load-bearing here: apply→branch→execute order), **3** (tool arguments — the decisions list), **4** (tool-output handling — branching on the apply summary), and **5** (end-state — published + execution + status machine). Not category 6 (strategy — Step 5's alone).

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v -k "approval_decision or approved_campaign or execution_result"` | `ApprovalDecision` validates + rejects bad enum/extras; transfer models round-trip. |
| Approvals wrappers | `.venv/bin/python -m pytest tests/test_step_7.py -v -k "approval or decision"` | `record_approval_decision` cascade (approved/rejected/edit_requested), `get_pending_approvals` event-scoped, `reset_approval_to_pending` clears notes. |
| Apply tool | `.venv/bin/python -m pytest tests/test_step_7.py -v -k apply` | `apply_approval_decisions` buckets correctly; persists every item. |
| Redraft | `.venv/bin/python -m pytest tests/test_step_7.py -v -k redraft` | Redraft mode reads edit_requested, overwrites copy, resets approval to pending; cap refuses past `MAX_REDRAFT_CYCLES`. |
| Execution | `.venv/bin/python -m pytest tests/test_step_7.py -v -k execute` | Route dispatch (poster/tshirt → shopify+printful, social_only → social); success → published + execution; failure → failure path. Stubbed helpers; no live calls. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–7 unit tests green; no regression. |
| Import check | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Coordinator builds with the new tools; graph unchanged (still 9 nodes). |
| **Tier 1 — HITL gate (deterministic, mocked, CI)** | `.venv/bin/python -m pytest tests/evals/test_step_7_trace.py -v` | (T1-a)–(T1-f). Zero live calls; single run authoritative. The gate `main` stays green against. |
| Behavioral branch probe (deliberate) | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_7_protocol.py -v` | Protocol order pass rate ≥ 95%/20. Requires `GOOGLE_API_KEY`. **Not a merge gate.** |

---

## Risks

| Risk | Mitigation |
| --- | --- |
| **Building to the docs' wrong HITL model** (decisions recorded "on resume" inside the function) | The function never re-runs (spikes). Separate `apply_approval_decisions` tool records; execute/redraft read persisted state. Spec corrections fix `db-wrapper-inventory.md`:210 + arch diagram. |
| **List payload doesn't round-trip** through `FunctionResponse.response` | Asserted in Tier-1 (T1-a). Fallback: ~15-line extension to `spike/adk_workflow_hitl_spike.py` claim 2 (existing spike only passed a flat dict). |
| **Coordinator mis-orders the protocol** (execute before apply; redraft doesn't loop; cap ignored) | Prompt protocol section (first-class) + behavioral repetition eval. Tool-level cap is robust to mis-ordering (counts actual invocations). |
| **Redraft loop spins** | Tool-level hard cap in `tool_context.state` (default 3) + prompt rule + explicit ADK iteration cap. Gap 1 closed this step. |
| **Cap counter lost across suspend** | Lives in session state; Tier-1 (T1-e) proves it survives the park. |
| **Operator never responds** | By design — operator-presence assumption; no timeout (`01-requirements.md`:149). Honest boundary: in-memory session is process-lifetime-bound; persistent session service for durable resume (enterprise/Cloud Run). |
| **Mixed batch ambiguity** | Canonical resolve-then-execute (redraft to resolution, then one execute). Interleaved is the documented alternative with a user veto point. |
| **Mock-handler clobber** on new approvals/campaigns handlers | One combined handler per `(tool, collection)`, branching on `status` — never two (confirmed memory). |
| **Live Shopify/Printful flake** | Out of this step (Option 1) — helpers stubbed at seam, CI never hits live; live wiring is a tracked demo-prep task. Internal Printful poll-loop structure is real so only the helper body swaps. |
| **`operator_notes` muddiness** | Resolved: redraft is a pure state-consumer (reads persisted `edit_requested` notes); `operator_notes` param retained only for D-030 signature stability + unit injection, off the production path. |
| **Treating this as a second strategic node / a post-approval Workflow** | Rejected by design — layer-2 composition on operator input (`agentic-model.md`:56), single iterating capabilities, not an ordered graph. Revisit only when `record_outcomes` adds a second ordered post-approval step. |

---

## Env vars

| Var | Purpose | Default |
| --- | --- | --- |
| `MAX_REDRAFT_CYCLES` | New — tool-level redraft cap (Gap 1) | `3` |
| `SHOPIFY_STORE_URL`, `SHOPIFY_ADMIN_TOKEN` | Existing — live execution (demo-prep; unused while helpers stubbed) | required at demo prep |
| `PRINTFUL_TOKEN` | Existing — live execution (demo-prep; unused while helpers stubbed) | required at demo prep |
| `GEMINI_COORDINATOR_MODEL` | Existing — coordinator (now runs the post-approval protocol) | `gemini-2.5-flash` |
| `GEMINI_MODEL` | Existing — redraft copy reuses it (same as Step 6) | `gemini-2.5-flash-lite` |

No new model env var — redraft copy reuses `GEMINI_MODEL` (it is the same `_draft_copy_for_asset` call). Execution makes no LLM call.

---

## Output consumed by

- **`record_outcomes` (Step 8, capability 9)** — reads executed campaigns / published assets to write `performance` metrics. Step 8 is the second ordered post-approval step; if it lands deterministic, reconsider folding execute + record into a small post-approval workflow (noted in § Why this is layer-2).
- **The coordinator / demo** — the HITL beat (operator scrolls the queue, approves) and the execution beat (Shopify draft, Printful mockup, social queued; MongoDB collections populated) — Event 1 full flow, `strategic-agent-reframe.md` § Demo coherence. The Printful `mockup_url` is the key visible artifact (live at demo prep).

---

## Out of scope: queue-level redo (enterprise path, designed-not-built)

A precise scope boundary, because two "redo" semantics are easy to conflate:

- **Item-level edit** — "I like this asset, fix its *copy*" — is said *at the item* (`edit_requested` + notes → copy redraft). **In scope; built this step.**
- **Queue-level redo** — "the *selection* is wrong, rebuild the queue" — is a distinct operation that goes back to **Step 5 (`propose_review_queue`)**, the strategic node. **Not built.**

Queue-redo is excluded from the MVP deliberately: it is not a spec'd HITL option (`01-requirements.md`:245-250 are per-item only), the demo's strategic story is cross-*event* queue variation rather than within-event correction, and it is a disproportionate lift — by approval time Step 6 has moved every asset to `campaign_draft_created` and written campaigns + approvals, so a true rebuild is a **destructive rollback**: reset the assets to `scored`, clear queue assignments, delete the campaigns/approvals, then re-run Step 5 — ideally **with operator steering** ("more exploration," "grittier shots"), itself a new input to the strategic node.

**No retrofit cost from deferring.** Queue-redo would be a *separate coordinator tool* (`repropose_queue(event_id, steering)`), **not** a new value in the per-item `ApprovalDecision` enum. The per-item contract this step builds stays clean and is unaffected; queue-redo bolts on later. This is the textbook design-now / build-later case — recorded here and in D-031, not implemented.

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

Doc-only; per CLAUDE.md every `docs/specs/` change needs a `tracking.md` D-entry.

1. **New D-entry (D-031): capabilities 7/8 are coordinator-plane; HITL resume mechanics.** Captures: (a) capabilities 7–9 live coordinator-side, **not** in the workflow graph (`02-architecture.md`:389) — Step 7 adds **zero** graph nodes; (b) **the resume-payload spine** — `LongRunningFunctionTool` function does not re-run on resume; payload goes to the LLM; a separate `apply_approval_decisions` tool persists decisions; execute/redraft are pure consumers of persisted Mongo state (D-022 philosophy); (c) **resolve-then-execute** mixed-batch flow (interleaved documented as the alternative); (d) redraft is a state-consumer reading persisted `edit_requested` notes — `operator_notes` retained only for signature stability (reconciles D-030); (e) **Gap 1 closed** — tool-level redraft cap + prompt 3-cycle rule + explicit ADK iteration cap; (f) operator-presence/no-timeout assumption + the in-memory-session process-lifetime boundary; (g) execution stubbed-at-seam (Option 1), live wiring a demo-prep task; route-driven channel selection (D-030); (h) this is **layer-2 composition, not the anti-pattern and not a second strategic node** (`agentic-model.md`:56); (i) the **display batch** is grouped by queue half (exploitation/exploration), carries per-item narrative + copy + `content_url`, and is keyed by `approval_id` (grouping presentational; decision identity is `approval_id`) — the *presentation surface* (a lightweight app posting the structured `FunctionResponse`) is a separate demo-prep track, not Step 7 agent scope; (j) **queue-level redo** (rebuild via Step 5 with operator steering) is **designed-not-built** — a separate future `repropose_queue` tool, *not* a per-item decision value, so deferring it carries no retrofit cost (distinct from in-scope item-level copy `edit_requested`). Refines D-024 (coordinator-over-workflow), D-030 (redraft deferral, route mapping), D-022 (state on document).
2. **`docs/db-wrapper-inventory.md`** — **correct line 210**: `record_approval_decision` is **not** "called by `request_human_approval` on resume" (the function doesn't re-run); it is called by `apply_approval_decisions`. Add `apply_approval_decisions`, `reset_approval_to_pending`, `get_edit_requested_campaigns` to the inventory; event-scope `get_pending_approvals` / `get_approved_campaigns` signatures.
3. **`docs/specs/02-architecture.md`** — fix the `request_human_approval` MCP-call block (287-293) to reflect the gate (no writes) + `apply_approval_decisions` (writes); note the Printful poll is an internal loop, not a `LongRunningFunctionTool` (reconciles 328 vs 402); note capabilities 7/8 are coordinator `FunctionTool`s. Fix the stale tech-stack line 13 ("Single `LlmAgent` … No `Workflow` graph") which predates D-024 — out-of-scope nicety, flag only.
4. **`docs/safety-measures.md`** — mark Gap 1 closed by Step 7 (tool-level cap + prompt rule + ADK iteration cap value); record the chosen iteration-cap number.
5. **`docs/specs/01-requirements.md`** — confirm capability 7's resume contract (per-item decisions list) and that the redraft branch is implemented here (closes the D-030 reservation).
6. **`CLAUDE.md` § ADK-Specific Rules** — record the explicit ADK iteration-cap value (per `safety-measures.md`:93).

Sequence on this branch: (1) housekeeping commit (items 1–6, doc-only) → (2) plan + tasks gates → (3) Phase A implementation + Tier-1 HITL eval → (4) Phase B implementation + full Tier-1 eval → (5) behavioral probe (deliberate) → (6) merge to `main` with the updated "Next action" in `CLAUDE.md`.

---

## What changed from prior planning docs

- **First coordinator-plane step** — capabilities leave the workflow graph; zero new nodes. The architectural inflection of the back half.
- **The HITL resume mechanics are corrected against the source docs** — the function does not re-run on resume; `apply_approval_decisions` is a new, separate tool; execute/redraft consume persisted state. Fixes `db-wrapper-inventory.md`:210 and the arch diagram.
- **Redraft implemented (D-030 reservation closed)** as a state-consumer, not via the `operator_notes` param (retained only for signature stability).
- **Gap 1 closed** — the redraft cap lands with the capability that triggers it, per `safety-measures.md`:59.
- **Execution stubbed at the seam** (Option 1) — full capability + status machine built/tested; live Shopify/Printful is demo-prep.
- **Coordinator prompt is first-class** — a stateful multi-tool protocol, not a one-liner; the highest-risk surface, asserted by the behavioral eval.
- **Eval is two-part** — a deterministic mocked Tier-1 HITL gate + a repetition-based behavioral protocol probe (coordinator-level, multi-turn, scripted `FunctionResponse`), a different seam from Steps 1–6's workflow-dispatch evals.
