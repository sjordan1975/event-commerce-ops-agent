# Step 6 — `draft_campaigns_for_queue`: Implementation Plan

## Context

Step 6 delivers `draft_campaigns_for_queue` — capability 6 of the nine. For every asset the strategist surfaced in Step 5's review queue, it generates campaign copy (headline, caption, hashtags) grounded in the Step 2 event narrative, derives the product/platform target from the asset's persisted `product_route`, computes a timing recommendation from event `timeliness`, and writes a `campaigns` draft + a `pending` `approvals` entry per item, transitioning each drafted asset to `status="campaign_draft_created"`.

This is **not** a second strategic node. Step 5 (`propose_review_queue`) is and remains the project's one and only in-graph `LlmAgent` node (D-029). Step 6 returns to the **`FunctionNode` + internal `genai` structured-output** pattern proven in Steps 2 (`build_event_context`) and 4 (`score_assets_with_vision`): a deterministic node whose body iterates queue members, calls an internal LLM helper per item, and drives the Mongo writes. The architecture diagram is explicit — `draft_campaigns_for_queue (FunctionNode)` (`02-architecture.md` line 373). Copy generation is **bounded LLM-at-the-node** work (type-1: a fixed artifact per item), not judgment-under-ambiguity. The narrative substrate is what makes the copy specific ("Messi ends France's reign in extra-time thriller") rather than generic ("Argentina beats France") — that grounding is the demo's load-bearing claim for this capability, but it is a *quality* property of a bounded task, not a strategic decision.

Prerequisite: Step 5 (`propose_review_queue`) is merged to `main`. The graph is `START → ingest_event_batch → build_event_context → find_similar_assets → score_assets_with_vision → prepare_queue_candidates → propose_review_queue → persist_review_queue`. Step 6 extends it with **one** node, `draft_campaigns_for_queue`, between `persist_review_queue` and `END`.

---

## Architecture decision: a `FunctionNode`, not a second `LlmAgent` node

The temptation, having just built the `LlmAgent` node in Step 5, is to reach for it again. Resisted, deliberately:

- **The spec is explicit.** `02-architecture.md` line 373 lists `draft_campaigns_for_queue (FunctionNode)`. Only `propose_review_queue` is the `LlmAgent` node (line 367).
- **It is conceptually correct.** Per the reframe, *exactly one* capability is the strategic decision; "most capabilities remain LLM-at-the-node-level (bounded, LLM-using-tools)" (`strategic-agent-reframe.md` § What this is not). Copy generation is one of those — the action space per item is "write copy for this asset using this narrative," not "decide what merits surfacing." Making it an agent node would blur the one structural fact the architecture encodes: where judgment lives.
- **It reuses a proven pattern with zero new ADK unknowns.** Step 4's `_score_asset_with_vision` (sync `genai` call wrapped in `asyncio.to_thread`, `response_schema=<PydanticModel>`, parsed via `model_validate_json`) is copied wholesale, swapping the image+vision prompt for a text+narrative prompt. No spike needed — the mechanics are identical to Step 4. The eval-mock seam is the same: patch the internal helper.

The output (`campaigns` + `approvals` documents) is byte-identical to what an agent node would produce; the difference is that the graph correctly reads "1 agent node + N deterministic nodes," and Step 6 stays on the deterministic side of that line.

---

## What this capability delivers

Realized as **one workflow node**, `draft_campaigns_for_queue` (`FunctionNode`), appended to the graph after `persist_review_queue`:

1. **Reads `event_id` from state** (written by the upstream ingest node, like every other node).
2. **Fetches the queue members from persisted state** — `get_assets_for_event(event_id, status="scored")`, then keeps only assets with `queue_type is not None`. Un-surfaced discovery-pool assets carry `queue_type=None` (Step 5's un-surfaced remainder) and are **not drafted**. This reads the queue back from Mongo rather than from session state, per D-022 (the queue is persisted onto the asset, re-renderable from the DB) — the same reason Step 5 persisted `queue_rank`/`queue_rationale`.
3. **Per queue member, generates copy** via the internal `_draft_copy_for_asset` helper — a single `genai` structured-output call returning `GeneratedCopy` (headline, caption, hashtags). The prompt is grounded in: the event narrative angle + key figures (copy substrate, D-016), the asset's `queue_rationale` (why it's in the queue), its `product_route`, `detected_subjects`, and `scores`. **The copy LLM consumes Step 4's *derived* signals (`detected_subjects`, `scores`) + the narrative — not the raw image** (a deliberate MVP choice: Vision already extracted the salient content, so re-sending image bytes is unnecessary cost; this also keeps the call text-only). This is the only point worth noting for a reviewer who expects the copy step to "see" the photo.

**What `detected_subjects` is — and is not — for here.** It is an **identity / commercial signal** (the family of `identity_score` and `player_context.commercial_signal`): *a recognizable, merch-driving person is in this frame* (Messi sells; an anonymous defender does not). It tells the copy LLM **who to name for commercial pull** — not *what is happening in the photo*. It carries names, not scene content. Consequently the copy can ground at the **event-narrative + identity** level (*"Messi caps Argentina's extra-time upset — limited edition print"*) but **not** at the photographed-action level (*"Messi's goal kick"*): the action/moment is image-level visual detail that no upstream signal captures (Vision emits scores + subject names only; Step 5's rationale never saw the image either). Action-level specificity is **explicitly out of MVP scope** and handled by demo-corpus curation (see § Grounding granularity below).
4. **Derives the campaign fields mechanically** — `product_type` and `platform_target` from `product_route` (see § Route mapping); `timing_recommendation` from event `timeliness` (deterministic helper).
5. **Persists one campaign + one approval per item** via the bundled `submit_campaign_for_review` wrapper: insert `campaigns` draft, set the asset to `status="campaign_draft_created"` + link `campaign_id`, insert the `approvals` entry `status="pending"`.

Returns `{"event_id", "campaign_ids": [...], "approval_ids": [...], "drafts": [...]}` (the `drafts` list carries the per-item copy + route for the coordinator to present).

Consumed by `request_human_approval` (Step 7) — reads the `pending` approvals + their campaigns for operator review; and by the coordinator, which surfaces the drafts after dispatch.

### Idempotency falls out of the status transition

A normal re-run is a no-op for already-drafted assets: `submit_campaign_for_review` transitions the asset to `campaign_draft_created`, so the next fetch (`status="scored"` + `queue_type` set) no longer returns it. No explicit skip-guard is needed (cf. Step 4's `if asset.scores is not None: continue`); the status filter *is* the guard. This is the same idempotency posture as the rest of the pipeline.

### Redraft is deferred to Step 7

The stub's `operator_notes` parameter is **reserved but unused** in Step 6. Rationale: the shape of `operator_notes` is defined by Step 7's `request_human_approval` resume payload (per-item decision + `reviewer_notes`). Implementing the redraft branch now means inventing a downstream-defined contract with no consumer to validate it — and the redraft fetch targets assets already at `campaign_draft_created` (different fetch logic from first-pass), which would be designed and tested against a guessed payload. Step 6 implements **first-pass drafting only**; the signature carries `operator_notes: dict | None = None` so the surface is stable, with a docstring note that the redraft branch lands in Step 7 alongside the HITL loop that produces those notes. (`01-requirements.md` and `02-architecture.md` describe the redraft case; this plan scopes its *implementation* to Step 7. Recorded in D-030.)

---

## The capability surface (D-019 + D-021)

| Surface | Type | Notes |
| --- | --- | --- |
| `draft_campaigns_for_queue_node` | `FunctionNode` | New. Edge: `persist_review_queue → draft_campaigns_for_queue → END`. Reads `event_id`; writes `campaigns`/`approvals` via the bundled wrapper; returns `campaign_ids`/`approval_ids`/`drafts`. |
| `_node_draft_campaigns_for_queue` | adapter (`src/capabilities/__init__.py`) | Same `parameter_binding="state"` pattern as the four existing `FunctionNode` adapters. Reads `event_id` from state, calls `draft_campaigns_for_queue`, writes the result back to state. |

Internal Python pieces added this step (none agent-facing; the agent-facing surface is the workflow, dispatched by the unchanged `run_event_pipeline` shim):

| Piece | File | Purpose |
| --- | --- | --- |
| `_draft_copy_for_asset(narrative_context, item_context)` | `src/capabilities/drafts.py` | **Internal LLM helper** — one `genai` structured-output call (`response_schema=GeneratedCopy`), sync, wrapped by callers in `asyncio.to_thread`. Mirrors Step 4's `_score_asset_with_vision`. The eval-mock seam (patch this). |
| `_route_to_campaign_fields(product_route)` | `src/capabilities/drafts.py` | **Pure function** — maps `product_route → (product_type, platform_target)`. Unit-tested. |
| `_recommend_timing(timeliness, event)` | `src/capabilities/drafts.py` | **Pure function** — deterministic timing recommendation from event timeliness. Unit-tested. |
| `draft_campaigns_for_queue(event_id, operator_notes=None)` | `src/capabilities/drafts.py` (replaces stub) | The capability. Preconditions → fetch queue members → per-item copy → bundled write. `operator_notes` reserved (Step 7). |
| `submit_campaign_for_review(campaign)` | `src/db/campaigns.py` (new file) | One bundled domain write: `campaigns insert-many` + `assets update-many` (status + `campaign_id`) + `approvals insert-many` (pending). Returns `{"campaign_id", "approval_id"}`. |

`get_assets_for_event`, `get_event` reused unchanged. Per D-019, `MongoMCPClient` stays the only programmatic client.

---

## What the LLM does in this capability

Two LLM invocations across a Step 6 dispatch:

1. **Coordinator dispatch decision** (outside the workflow) — unchanged from Steps 1–5.
2. **The per-item copy-generation call** (the internal `_draft_copy_for_asset` helper, once per queue member) — **bounded generation**, not judgment. Single call, structured output, `response_schema=GeneratedCopy`. The action is fixed ("write grounded copy for this asset"); only the words vary. This is the same bounded-LLM-at-the-node role as `build_event_context` and `score_assets_with_vision`.

There is no strategic LLM call in Step 6. The strategic decision happened in Step 5.

### Per-item iteration (chosen consciously, not by Step-4 mimicry)

Copy is text-only, so a single batched call (all items → a list output) would be cheap and is what the reframe's § Batch nudges toward for trace legibility. **Per-item is chosen anyway**, for three reasons specific to this node:

- **Grounding isolation** — each prompt is scoped to one asset's rationale/route/subjects, which keeps each draft tightly grounded and the prompt simple.
- **No id echo-back risk** — a batched output forces the model to echo `asset_id` per item, reintroducing the "invented/dropped id" defensive-join problem Step 5's `persist` had to handle. Per-item sidesteps it entirely.
- **Trace legibility is already satisfied at the node level** — the workflow graph (and the demo trace) shows *one* `draft_campaigns_for_queue` node regardless of how many internal calls it makes. The batched-vs-per-item choice only affects the LLM-call count, and cardinality here is small (queue members, ~5–15, not Vision's ~400), so N calls is acceptable.

This reuses Step 4's exact `asyncio.to_thread(_helper, ...)` loop and its eval-mock seam verbatim — the lowest-risk path.

### Model: reuse `GEMINI_MODEL` (no new env var)

The copy node runs on the **existing `GEMINI_MODEL`** (default `gemini-2.5-flash-lite`) — the var CLAUDE.md designates for "workflow nodes and internal-LLM helpers like `build_event_context`." No `GEMINI_DRAFT_MODEL` is introduced.

The right precedent is `build_event_context`: also grounded *text generation*, also on `GEMINI_MODEL` (flash-lite). flash-lite's documented weakness is the coordinator's *judgment/routing* decisions, not generation; the vision/queue dedicated-flash vars (D-028, D-029) were justified by judgment density, which does not apply to deriving copy from an already-built narrative. If flash-lite is good enough to write the narrative, it is hard to argue it is not good enough to write copy grounded in that narrative. A dedicated `GEMINI_DRAFT_MODEL` (default flash) is introduced **only if** a quality probe (the optional grounding check below) empirically shows flash-lite copy is generic — that would be a remediation-ladder step (model swap), not a default. Recorded in D-030 (model-default discipline).

The copy call carries `generate_content_config=GenerateContentConfig(max_output_tokens=<bounded>)` — the spend bound per `safety-measures.md` Gap 2 (sized for one item's headline+caption+hashtags; per-item so it does not scale with N within a single call).

---

## Grounding granularity (and the post-demo trajectory)

Step 6 copy grounds at **two levels**, and deliberately stops there:

- **Event-narrative level** (`narrative_angle`, `key_figures`) — what the event is about. *"Messi ends France's reign in an extra-time thriller."*
- **Identity level** (`detected_subjects`) — *who* (a merch-driving person) is in this frame. Lets the copy correctly name Messi on a Messi photo and correctly *not* name him on a crowd shot.

It does **not** ground at the **photographed-action level** (*"Messi's goal kick"*). That moment-specific visual detail is not in the substrate: Vision (the only capability that sees pixels) emits `scores` + subject *names* only; Step 5's `queue_rationale` never saw the image either. This is an accepted MVP boundary, confirmed with the product owner:

- **It meets the requirement's own bar.** `01-requirements.md`'s differentiator is *"Argentina beats France — poster"* (generic) vs *"Messi ends France's reign in extra-time thriller — limited edition print"* (narrative-grounded). That contrast is **event + identity**, which this plan delivers. "Goal-kick"-level specificity is a *higher* bar than the spec sets.
- **Action-dependent shots are curated out, not coded around.** The demo corpus excludes photos whose appeal *depends* on naming a specific action — a corpus decision, not a code decision. Cross-ref: `docs/plans/demo-corpus.md` (the tracked corpus deliverable) should note this exclusion when it lands.

**Post-demo / enterprise trajectory (recorded, not built).** When action/scene specificity becomes a goal, the conceptually correct move is to **enrich the perception layer, not pass pixels to the writer.** The boundary the architecture keeps sharp is **perception vs. composition**: Vision is the *one* capability that touches pixels and converts them into durable, structured facts; everything downstream (queue assembly, copy, redraft) is *composition* that reasons over those facts as text. So the right extension is a persisted `scene_description` field on the Vision output (a sibling of `detected_subjects`, consumed as text by both Step 5 and Step 6) — **not** sending the image to the copy LLM. Image-to-copy is rejected as the production answer because it would: (1) pay for perception `O(images × redraft cycles)` instead of once; (2) de-synchronize the system's view of a photo (Vision's "Messi, identity 0.9" vs the writer's independent "a player in blue") with no shared ground truth; (3) leave no durable, auditable representation of image content; (4) break the perception/composition boundary the rest of the system is built on (the same boundary that keeps Step 6 a `FunctionNode`, not a second `LlmAgent` node). Raw-image-passing is right only when a consumer's visual needs are *unpredictable* (open-ended visual Q&A); campaign copy's needs are bounded and known, which is the textbook case for structured extraction. This is an enterprise-path note for `tracking.md` (D-030), not Step 6 work.

---

## Enterprise trajectory (post-MVP, recorded not built)

Several design discussions during planning converged on the same conclusion: the MVP's copy is faithful but **bounded**, and the bound is set *upstream* of Step 6, not in it. Capturing the trajectory here so it lives in one place rather than only in review chat. **None of this is MVP work** (Hard Constraint #8); the seed-and-operator-framed approach is the correct call for a curated 3-minute demo. This is the map of where enterprise depth gets added.

### Why the MVP narrative is bounded — and where the bound sits

Step 6 copy grounds in the Step 2 event narrative. That narrative's substance comes from **four sources**, and only one is genuine system retrieval:

| Ingredient | Source | Kind |
| --- | --- | --- |
| The angle / significance ("upset") | **Operator chat**, LLM-parsed (`coordinator_system.md` extracts `outcome_type`; the clarification flow refuses to *guess* it) | *Borrowed* |
| Grounding facts (e.g. a key figure's bio) | `player_context` collection | *Seeded* (static, hand-authored) |
| Commercial baseline (what sold for this outcome) | `aggregate_performance_for_events` | *Derived* (real retrieval) |
| The framing (composing the above into a typed `EventNarrative`) | the narrative LLM | *Composed* |

The consequence: **the system does not *understand* the event** — it cannot independently tell an upset from an expected win (no odds, rankings, stakes, or in-match drama). Its grasp of significance is operator-supplied and decorated with seeded facts. The agent's genuine intelligence is downstream — queue assembly (the one strategic decision) and grounded copy — operating *on top of* a human-supplied frame. This is on-brand for the MVP (HITL by design; speed-of-monetization value prop; factual safety from refusing to infer significance), but it is the exact seam where enterprise depth is added.

The `player_context` "RAG" is also lighter than the term implies: `find_players_for_teams` is a **plain `find` (`team $in [...]`) over a hand-seeded collection** — no embeddings, no vector search, no live source. The only true vector search in the system is on `assets` (Step 3). So the narrative side is "lookup-augmented generation," not semantic RAG.

### Two orthogonal axes of enterprise richness

Both feed Step 6 copy; they are independent and additive.

- **Axis 1 — richer *factual / significance* substrate (the Step 2 axis, the higher-value one).** Replace the static seed + operator-framed angle with genuine retrieval over a live/large corpus: real semantic RAG over a player/news/history corpus (recent form, head-to-head, this match's storyline), and live sources (sports-data API, news feed, social trends at match time). The decisive shift is **angle from *echo* to *derive***: pull pre-match odds/rankings → the system *confirms* "upset" itself; pull match events → drama ("the hat-trick that wasn't enough"); pull standings → stakes ("defending champions eliminated"). **The payoff is autonomy, not just richness** — it removes the dependency on a well-framed operator prompt. At scale you cannot rely on every operator typing a clean "upset" line; a system that ingests *"photos from the France–Argentina match"* and derives the rest is the scalable version. Copy richness in Step 6 is the downstream side effect.

- **Axis 2 — richer *visual* substrate (the Step 4 / perception axis).** A persisted Vision `scene_description` so copy (and Step 5) can speak to the photo itself — enriching the perception layer, **not** passing the image to the writer. Full rationale and the perception-vs-composition principle are in § Grounding granularity above; not repeated here.

### The partner-track angle

The MongoDB showcase here is **not primarily vector search** — it is that **MongoDB's MCP is trusted as the agent's entire state and persistence backbone, and it held up end to end.** Per D-019, `MongoMCPClient` (wrapping `McpToolset`) is the *only* programmatic data client; every one of the nine capabilities reads and writes through it across six collections (`events`, `assets`, `campaigns`, `approvals`, `performance`, `player_context`). The `assets` document is the durable state layer — the `ingested → scored → campaign_draft_created → executing → published` status machine makes the agent's trajectory resumable across ADK sessions, and D-022's persistence philosophy (persist composed artifacts — the event narrative, the queue fields, the campaign drafts — onto their documents rather than thread them through session state) *relies* on the MCP being solid enough to be the system of record. That is the hackathon's partner-track spirit (highlight the partner's MCP): not "we used a flashy feature once," but "the partner's MCP carried all the back-and-forth state, and we built on it confidently."

Vector search (asset similarity, Step 3) is the most *visible* single MCP call, but it is one capability among many — not the whole partner story. So the enterprise expansion here is **additive, not corrective**: Axis 1 on MongoDB would add a *second* vector index (a player/news corpus) so vector search powers both *which images* (asset similarity) **and** *which facts / which significance* (narrative grounding) — deepening an integration that is already load-bearing across the entire system, rather than finally making it matter in a second place. The autonomy story and the dual-vector-search story are the same investment.

---

## What the capability does internally

```text
draft_campaigns_for_queue (FunctionNode)
    event_id = ctx.state["event_id"]
    event = get_event(event_id)                       # narrative + timeliness substrate
    assets = get_assets_for_event(event_id, status="scored")
    # preconditions (defense-in-depth; graph order guarantees these at this node):
    #   - event missing                → "call ingest_event_batch first"
    #   - no scored assets at all      → "call score_assets_with_vision first"
    #   - event.event_narrative None   → "call build_event_context first"
    queued = [a for a in assets if a.queue_type is not None]   # un-surfaced (queue_type None) skipped
    if not queued: return {"event_id", "campaign_ids": [], "approval_ids": [], "drafts": []}
        # zero SURFACED assets is a valid degenerate outcome, NOT a precondition error (see below)
    narrative_context = {angle, key_figures} from event.event_narrative
    campaign_ids, approval_ids, drafts = [], [], []
    for asset in queued:                               # ordered by (queue_type, queue_rank)
        item_context = {queue_type, queue_rationale, product_route, detected_subjects, scores}
        copy = await asyncio.to_thread(_draft_copy_for_asset, narrative_context, item_context)  # GeneratedCopy
        product_type, platform_target = _route_to_campaign_fields(asset.product_route)
        campaign = Campaign(
            campaign_id=uuid, asset_id=asset.asset_id, event_id=event_id,
            product_type=product_type, generated_copy=copy, platform_target=platform_target,
            timing_recommendation=_recommend_timing(event.timeliness, event),
            status="draft", created_at=now, execution=None,
        )
        result = await submit_campaign_for_review(campaign)   # {campaign_id, approval_id}
        campaign_ids.append(result["campaign_id"]); approval_ids.append(result["approval_id"])
        drafts.append({asset_id, product_route, headline, caption, timing_recommendation, queue_rationale})
    return {"event_id": event_id, "campaign_ids": ..., "approval_ids": ..., "drafts": ...}
```

`submit_campaign_for_review` (the bundled write):

```text
submit_campaign_for_review(campaign) -> {campaign_id, approval_id}
    approval_id = uuid
    campaigns.insert-many   [campaign.model_dump(mode="json")]
    assets.update-many      filter {asset_id}, $set {status: "campaign_draft_created", campaign_id}
    approvals.insert-many   [{approval_id, campaign_id, asset_id, status: "pending",
                              reviewer_notes: None, created_at: now, decided_at: None}]
    return {"campaign_id": campaign.campaign_id, "approval_id": approval_id}
```

**Three writes, one logical operation** (D-019 / db-wrapper-inventory § "bundling is correct here"): a campaign with no approval entry is an orphan; an approval pointing at no campaign is dangling; an asset at `campaign_draft_created` with no campaign is incoherent. They are issued as three sequential MCP calls — **not a transaction** (the MongoDB MCP surface is single-document; no multi-doc atomicity). For MVP this is acceptable (single-operator, no concurrent writers); flagged in § Risks. The new `approvals` entry is always created fresh and `pending` with empty `reviewer_notes` — `reviewer_notes` is the *human's* approval-time field (written by Step 7), never an input here.

**Preconditions.** Mirrors `score_assets_with_vision`: hard-refuse with a self-correcting `PreconditionError(capability="draft_campaigns_for_queue", context=event_id, missing={...})` for the *genuinely missing prerequisites* — the event is missing (`call ingest_event_batch first`), no scored assets exist at all (`call score_assets_with_vision first`), or the narrative is missing (`call build_event_context first`). Under the D-024 graph order all hold at this node; the check is defense-in-depth for direct/unit calls.

**Zero *surfaced* assets is a valid degenerate outcome, not a precondition failure.** If scored assets exist but none carry `queue_type` (the queue surfaced nothing), the node returns an **empty result** (`campaign_ids: []`, etc.) rather than raising — consistent with Step 5's "empty pools are valid" stance and the reframe's framing. This is mechanically reachable (all assets below the exploitation cutoff *and* the strategist surfaces nothing from discovery), so it is not an error. Crucially, raising "call propose_review_queue first" here would **misfire** under the graph order (that node always ran) — the absence of `queue_type` does not reliably signal "queue step skipped," because queue assignment leaves `status="scored"` unchanged (D-029). So the surfaced-none case is handled as empty-valid, and only the three signals above (which *do* distinguish missing prerequisites) raise.

---

## Route mapping (a spec wrinkle resolved explicitly)

`product_route` has three values; `campaigns.product_type` is `poster | tshirt` and `campaigns.platform_target` is `shopify | printful | social`. Resolution for MVP:

| `product_route` | `product_type` | `platform_target` |
| --- | --- | --- |
| `poster` | `poster` | `shopify` |
| `tshirt` | `tshirt` | `shopify` |
| `social_only` | `None` | `social` |
| `None` (defensive) | `None` | `social` |

- **`platform_target` is a largely redundant label.** Execution (Step 7) selects channels off `product_route` directly (`02-architecture.md`: poster/tshirt → Shopify + Printful; social_only → social). The campaign's single `platform_target` is a display/grouping hint, not the execution driver. A single value is therefore fine; **the discriminator is consistency with how Step 7 reads it** — `shopify` for physical goods (the storefront is the primary commerce surface; the Printful mockup is a fulfillment artifact produced at execution, not the campaign's target), `social` for social_only. Noted so Step 7 does not re-derive a conflicting convention. (The schema lists `printful` as a possible value; it is reserved for the enterprise multi-route path, `01-requirements.md` line 46, not used in the MVP one-campaign-per-asset model.)
- **Defensive `product_route=None`** — a surfaced discovery item *should* carry a `product_route` (Step 5's LLM assigns one), but the field is nullable and the model could leave it null. The mapping treats `None` as `social_only` (`product_type=None`, `platform_target=social`) — the safe, no-physical-fulfillment default — rather than raising. Unit-tested.
- **MVP one-campaign-per-asset.** Exactly one campaign per queued asset, for its single route. Multi-route (poster + social in parallel) is the enterprise path (`01-requirements.md` line 46) and explicitly out of scope.

---

## Pydantic models (new)

```python
# Persisted-document models — extra="forbid" (like Event/Asset).
class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    campaign_id: str
    asset_id: str
    status: str = "pending"                 # pending | approved | rejected | edit_requested
    reviewer_notes: str | None = None        # human's field; written by Step 7
    created_at: str
    decided_at: str | None = None

class Campaign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    asset_id: str
    event_id: str
    product_type: Literal["poster", "tshirt"] | None   # None for social_only
    generated_copy: "GeneratedCopy"
    platform_target: Literal["shopify", "printful", "social"]
    timing_recommendation: str
    status: str = "draft"                    # draft | approved | rejected | executed
    created_at: str
    execution: dict | None = None            # written by execute_approved_campaigns (Step 7)

# LLM output schema — NO extra="forbid" (Gemini response_schema rejects
# additionalProperties:false; the recurring Steps-2/4/5 constraint).
class GeneratedCopy(BaseModel):
    headline: str
    caption: str
    hashtags: list[str]
```

The `extra="forbid"` split is deliberate and load-bearing: `Campaign`/`Approval` are document models that should reject typos (like `Event`/`Asset`); `GeneratedCopy` is fed to Gemini as a `response_schema`, which rejects `additionalProperties:false` — so it must omit `extra="forbid"`, exactly as `VisionScoringOutput`, `EventNarrative`, and `ReviewQueue` already do.

No modification to `Asset` is needed — `status` and `campaign_id` already exist; Step 6 is their first writer for the `campaign_draft_created` / linked-campaign state.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `GeneratedCopy`, `Campaign`, `Approval` models | `src/models.py` (extension) | LLM output schema + two persisted-document models |
| 2 | `submit_campaign_for_review` wrapper | `src/db/campaigns.py` (new) | Bundled `campaigns` insert + `assets` status/link update + `approvals` pending insert |
| 3 | `_route_to_campaign_fields` | `src/capabilities/drafts.py` | Pure route → (product_type, platform_target) map |
| 4 | `_recommend_timing` | `src/capabilities/drafts.py` | Pure deterministic timing from event timeliness |
| 5 | `_draft_copy_for_asset` + internal `genai` call | `src/capabilities/drafts.py` | Per-item copy generation; the eval-mock seam |
| 6 | `draft_campaigns_for_queue` | `src/capabilities/drafts.py` (replaces stub) | The capability: preconditions → fetch → per-item draft → bundled write |
| 7 | Draft-copy prompt | `prompts/v3/draft_campaign_copy.md` (new) | Grounded-copy prompt — narrative angle + key figures + per-item rationale/route/subjects; "specific, not generic" directive |
| 8 | adapter + node + graph edge | `src/capabilities/__init__.py` (modification) | `_node_draft_campaigns_for_queue`, `draft_campaigns_for_queue_node`; extend chain tuple to 9 elements |
| 9 | `run_event_pipeline` return | `src/agent.py` (modification) | Add `campaign_ids`/`approval_ids`/`drafts` to the returned state dict |
| 10 | Coordinator prompt | `prompts/v3/coordinator_system.md` (light edit) | One-line addition: after the pipeline returns, present the generated drafts (per item: headline, route, timing) alongside the queue |
| 11 | Conftest helpers | `tests/conftest.py` (extension) | `build_valid_generated_copy()`, `build_valid_campaign()`, `build_valid_approval()` |
| 12 | Tests — unit | `tests/test_step_6.py` (new), `tests/test_models.py` (extension) | Models; `_route_to_campaign_fields` (all four cases incl. None); `_recommend_timing`; `submit_campaign_for_review` envelope (three writes, correct `$set`, status transition, pending approval, no `reviewer_notes` input); `draft_campaigns_for_queue` (per-item copy via mocked helper, un-surfaced assets skipped, zero-surfaced → empty result, preconditions raise on missing event/narrative/scored-assets) |
| 13 | Tests — Tier 1 plumbing eval | `tests/evals/test_step_6_trace.py` (new) | Deterministic, internal helper mocked — per-item campaign+approval written, status transition, route mapping, un-surfaced skipped. Zero live calls; CI ship gate |
| 14 | Eval conftest extension | `tests/evals/conftest.py` (modification) | **Pre-seed queue-bearing assets** (see § Eval scaffolding decision); `_draft_copy_for_asset` mock control (Tier 1) |
| 15 | Tests — optional grounding probe | `tests/evals/test_step_6_grounding.py` (new, **not a merge gate**) | Live `_draft_copy_for_asset`; asserts generated headline/caption contains a seeded narrative-specific token (key-figure name / distinctive angle term). Quality probe, run deliberately |

---

## Dependency order

1. **Models** — `GeneratedCopy` (no `extra="forbid"`), `Campaign`, `Approval` (`extra="forbid"`).
2. **Conftest helpers** — `build_valid_generated_copy()`, `build_valid_campaign()`, `build_valid_approval()`.
3. **`submit_campaign_for_review` wrapper** — unit-tested via mocked client (asserts the three writes, the `$set` on assets, pending approval, no `reviewer_notes` input).
4. **Pure helpers** — `_route_to_campaign_fields` (four cases), `_recommend_timing` (timeliness → recommendation).
5. **Draft-copy prompt** — `prompts/v3/draft_campaign_copy.md`.
6. **`_draft_copy_for_asset`** — internal `genai` helper + mock seam (mirror Step 4's `_score_asset_with_vision`).
7. **`draft_campaigns_for_queue`** — preconditions + fetch + per-item loop + bundled write; unit-tested with mocked helper + mocked wrapper.
8. **Adapter + node + graph edge** (`src/capabilities/__init__.py`) — extend chain tuple to 9 elements.
9. **`run_event_pipeline`** returns drafts; coordinator prompt edit; verify `build_coordinator()/build_workflow()` import OK.
10. **Eval scaffolding** (`tests/evals/conftest.py`) — seed queued assets + `_draft_copy_for_asset` mock control.
11. **Tier 1 plumbing eval** (`tests/evals/test_step_6_trace.py`) — deterministic/mocked, single run, CI gate.
12. **Optional grounding probe** (`tests/evals/test_step_6_grounding.py`) — live, deliberate, not a merge gate.

---

## Draft-copy prompt template (load-bearing — grounding probe asserts on its output)

`prompts/v3/draft_campaign_copy.md` — formatted by `_draft_copy_for_asset` (Python `.format`). Shape:

```text
You are writing campaign copy for one product derived from a single sports-event photo.
Output JSON matching the GeneratedCopy schema (headline, caption, hashtags).

EVENT NARRATIVE (your grounding — use the specifics, do NOT write generic copy)
- narrative angle: {narrative_angle}
- key figures: {key_figures}

THIS ASSET
- why it's in the queue: {queue_rationale}
- product route: {product_route}        (poster / tshirt / social_only)
- subjects in frame: {detected_subjects}

WRITE THE COPY
- Headline: specific to THIS event, grounded in the narrative angle. "Messi ends France's
  reign in extra-time thriller" — not "Argentina beats France". The narrative is what makes
  it specific.
- GROUNDING GUARD (authoritative): only name a person if they appear in `subjects in frame`.
  Do NOT name a figure who is in the event's key figures but NOT in this image's subjects.
  Do NOT describe a specific action, pose, or moment (you are not shown the photo) — speak to
  the event and the people present, never to what they are doing in the frame.
- Caption: 1–2 sentences expanding the headline; tie it to the product route.
- Hashtags: 3–6, mixing event-specific (#ArgentinaVsFrance) and evergreen (#WorldCup2026) tags.
```

The "specific, not generic" directive + the worked example are the demo's grounding claim and what the optional grounding probe asserts against (a seeded key-figure name or angle term appears in the output). The **GROUNDING GUARD** is the Step-4-style hallucination guard, load-bearing for honesty: it stops the event-level narrative from leaking a name onto a frame that does not contain that person (the narrative says "Messi"; the photo is the crowd), and it forbids inventing photographed actions the substrate cannot back. Costs nothing; it is what makes the grounding claim faithful rather than confabulated.

---

## System prompt context

`prompts/v3/coordinator_system.md` gets a **one-line addition**: after `run_event_pipeline` returns, present the generated campaign drafts — per item, the headline, product route, and timing recommendation — alongside the proposed review queue, for operator review. (Full HITL approve/reject/edit is Step 7; Step 6 only produces and surfaces the drafts.) No other coordinator change; the workflow extends transparently beneath the dispatch tool, as in Steps 3–5.

---

## Evaluation

Step 6 is **bounded LLM-at-the-node** (the Step 4 category), not a strategic node (the Step 5 category). The eval posture follows Step 4, not Step 5: a deterministic mocked gate is the required CI artifact; there is no judgment-coherence pass-rate gate, because there is no judgment here once the copy call is mocked.

### Eval scaffolding decision (load-bearing — Step 6 is the first node that READS state a prior node WROTE)

The existing `_MockMCPClient` (`tests/evals/conftest.py`) is **write-recording / canned-read**: `update-many` records the call and returns `"ok"` without mutating any backing store, and `find` returns canned docs from a registered handler. Steps 1–5 never depended on read-after-write — Step 5's Tier 1 asserted the `save_queue_assignment` *write was issued*, never read the assets back. Step 6 is different: its node does `get_assets_for_event(event_id, status="scored")` and depends on the persisted `queue_type`/`product_route`/`queue_rationale` fields being present. The existing Step-5 `assets find` handler returns assets with `queue_type=None`, `status="ingested"` — so a naive full-pipeline Tier-1 run would have Step 6 read zero queued assets and draft nothing (assertions vacuously pass or fail confusingly, and it would hit the empty-valid branch for the wrong reason).

**Decision: pre-seed queue-bearing assets** (do *not* attempt to make the mock read-after-write). Register a Step-6 `(find, assets)` handler that, for the `status="scored"` filter, returns assets already carrying `status="scored"` + `queue_type` (exploitation/discovery) + `product_route` + `queue_rank` + `queue_rationale` + `scores` + `detected_subjects`. **The seed must span routes** — at least one `poster`, one `tshirt`, one `social_only` exploitation/discovery member — so the route-mapping assertion (T1-d) is meaningful; include one un-surfaced asset (`queue_type=None`) so the skip assertion (T1-c) has something to skip. This pre-seed *is* the Tier-1 fixture; it makes Step 6's read deterministic without coupling to Step 5's write path.

**Tier 1 — plumbing gate (deterministic, mocked, the merge gate).** `tests/evals/test_step_6_trace.py`. The internal `_draft_copy_for_asset` is patched to return a canned `GeneratedCopy` — **zero live model calls**, runs offline/CI with no `GOOGLE_API_KEY`. Deterministic → a **single run is authoritative**. A full `run_event_pipeline` dispatch (same Argentina-vs-France operator prompt as Steps 2–5) with upstream LLM surfaces patched (narrative, vision, queue via the existing seams) and a seeded queue. Asserts the code path:

- (T1-a) one `campaigns` draft per queued asset (insert with the canned copy, correct `product_type`/`platform_target` for each asset's route).
- (T1-b) one `approvals` entry per draft, `status="pending"`, linked `campaign_id`/`asset_id`, empty `reviewer_notes`.
- (T1-c) each drafted asset transitioned to `status="campaign_draft_created"` with its `campaign_id` linked; un-surfaced (`queue_type=None`) assets got **no** campaign/approval/status change.
- (T1-d) route mapping correct across poster / tshirt / social_only (and the defensive `None → social_only`).
- (T1-e) coordinator dispatched `run_event_pipeline` exactly once; reasoning text present pre-dispatch (CoT directive); `run_event_pipeline` return carries `campaign_ids`/`approval_ids`/`drafts`. On failure `dump_trace()`.

This is the gate `main` stays green against. It cannot flake on AI infra.

**Optional — grounding quality probe (live, deliberate, NOT a merge gate).** `tests/evals/test_step_6_grounding.py`. Runs the real `_draft_copy_for_asset` against a seeded narrative whose key figure / angle term is known, and asserts (a) the generated headline or caption **contains that token** (e.g. the key-figure surname, or a distinctive angle word) — i.e. the copy is grounded, not generic; and (b) the **hallucination guard holds** — for a seeded asset whose `detected_subjects` is empty (a crowd shot), the copy does **not** name a key figure absent from that frame. (a) is the grounding claim; (b) is the honesty claim (event-level narrative must not leak a name onto a frame that lacks the person). This is a *quality probe* for the demo's "specific, not generic" claim, not a strategy-coherence gate: copy-gen has no judgment-infra flakiness to isolate, so it does **not** carry Step 5's `EVAL_REPEAT=20` / transient-error-exclude machinery. Run it deliberately (a handful of runs) when validating demo copy quality. If it reveals generic copy, that triggers the remediation ladder (prompt language first → then, as a model-swap rung, introduce `GEMINI_DRAFT_MODEL=flash`) — never a heuristic. It is explicitly **not** part of the merge gate; Tier 1 + the unit suite are.

Step 6 exercises failure categories 4 (tool-output handling — the node reasons over the narrative/queue it's given) and 5 (end-state — campaigns + approvals persisted, status transitioned). Not category 6 (strategy coherence) — that is Step 5's alone.

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v -k "campaign or approval or generated_copy"` | `Campaign`/`Approval` validate + reject bad enums/extras; `GeneratedCopy` validates and round-trips via `model_validate_json`; `product_type=None` accepted. |
| Wrapper (unit) | `.venv/bin/python -m pytest tests/test_step_6.py -v -k submit` | `submit_campaign_for_review` issues `campaigns` insert + `assets` update (`$set` = status `campaign_draft_created` + `campaign_id`) + `approvals` insert (pending, no `reviewer_notes` input); returns `{campaign_id, approval_id}`. |
| Pure helpers (unit) | `.venv/bin/python -m pytest tests/test_step_6.py -v -k "route or timing"` | `_route_to_campaign_fields` correct for poster/tshirt/social_only/None; `_recommend_timing` deterministic from timeliness. |
| Capability (unit) | `.venv/bin/python -m pytest tests/test_step_6.py -v -k draft` | `draft_campaigns_for_queue` (mocked helper + wrapper): one draft per queued asset, un-surfaced (`queue_type=None`) skipped, zero-surfaced returns empty result (no raise), preconditions raise with the right `missing` keys on missing event / narrative / scored-assets. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–6 unit tests green; no regression. |
| Import check | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Graph builds with the 9-element chain. |
| **Tier 1 — plumbing gate (deterministic, mocked, CI)** | `.venv/bin/python -m pytest tests/evals/test_step_6_trace.py -v` | Assertions (T1-a)–(T1-e). Zero live calls; single run authoritative. The gate `main` stays green against. |
| Grounding probe (optional, deliberate) | `.venv/bin/python -m pytest tests/evals/test_step_6_grounding.py -v` | Generated copy contains the seeded narrative token. **Quality probe, not a merge gate** (requires `GOOGLE_API_KEY`). |

---

## Risks

| Risk | Mitigation |
| --- | --- |
| **Generic copy** — flash-lite produces "Argentina beats France" not the narrative-specific headline | Prompt names the rule + a worked example explicitly. The optional grounding probe measures it deliberately. If it surfaces, climb the ladder prompt-first; the model-swap rung is `GEMINI_DRAFT_MODEL=flash` — introduced only on evidence, not by default (model-default discipline, D-030). |
| **Name hallucination** — event-level narrative leaks a key figure's name onto a frame that does not contain them (narrative says "Messi"; photo is the crowd), or the copy invents a photographed action | Prompt **GROUNDING GUARD** makes `detected_subjects` authoritative for naming and forbids asserting unseen actions. The grounding probe asserts the guard on a seeded empty-`detected_subjects` (crowd) asset. This is the Step-4-style hallucination guard (failure category 4). |
| **Reaching for a second `LlmAgent` node** | Resisted by design — `02-architecture.md`:373 is explicit, and the reframe reserves the agent node for the one strategic decision. Step 6 is the Steps-2/4 `FunctionNode`+internal-`genai` pattern. |
| **No multi-doc transaction** for the bundled write | The three writes are sequential MCP calls, not atomic. Acceptable for MVP (single operator, no concurrent writers). A partial failure leaves a detectable inconsistency (campaign without approval) — flagged for the enterprise path; not closed in MVP. |
| **Inventing the redraft `operator_notes` contract early** | Deferred entirely to Step 7, where `request_human_approval` defines the payload. Step 6 reserves the param, implements first-pass only. |
| **`product_route=None` on a surfaced item** | `_route_to_campaign_fields` defensively maps `None → (None, social)` (social_only) rather than raising. Unit-tested. |
| **Drafting un-surfaced assets** | Fetch filters to `queue_type is not None`; un-surfaced discovery-pool assets (`queue_type=None`) are skipped. Asserted in unit + Tier 1. |
| **Re-run double-drafts** | Idempotent by construction — the `scored → campaign_draft_created` transition removes drafted assets from the next `status="scored"` fetch. No explicit skip-guard needed. |
| **`platform_target` convention drifts from Step 7 execution** | The mapping (poster/tshirt → shopify, social_only → social) is documented here as the convention Step 7 must read consistently; execution drives channels off `product_route` regardless, so `platform_target` is a label, not the driver. |
| **`GeneratedCopy` carries `extra="forbid"` and Gemini rejects it** | Explicitly omitted on `GeneratedCopy` (the LLM output schema), as on `VisionScoringOutput`/`EventNarrative`/`ReviewQueue`. Only the persisted-document models (`Campaign`/`Approval`) carry it. |

---

## Env vars

No new env vars. The copy node reuses **`GEMINI_MODEL`** (default `gemini-2.5-flash-lite`) — consistent with `build_event_context`, the comparable grounded-text-generation node. `GEMINI_DRAFT_MODEL` (default flash) is introduced only if the grounding probe shows flash-lite copy is generic (a remediation-ladder model swap, not a default).

| Var | Purpose | Default |
| --- | --- | --- |
| `GEMINI_MODEL` | Existing — workflow nodes + internal-LLM helpers (now incl. the copy node) | `gemini-2.5-flash-lite` |
| `GOOGLE_API_KEY` | Existing — `google.genai` model auth | required |
| `GEMINI_COORDINATOR_MODEL` | Existing — coordinator | `gemini-2.5-flash` |

---

## Output consumed by

- **`request_human_approval` (Step 7)** — reads the `pending` `approvals` + their `campaigns` for operator review; the HITL gate suspends on this batch. The redraft branch (operator `edit_requested` → `draft_campaigns_for_queue(event_id, operator_notes)`) lands in Step 7 with the loop wiring.
- **The coordinator** — surfaces the generated drafts (per item: headline, route, timing) alongside the queue after dispatch.
- **The trace/demo** — the "generate campaign drafts" beat (Event 1 full flow, ~1:30 per `strategic-agent-reframe.md` § Demo coherence). The grounded, narrative-specific headline ("Messi ends France's reign…") is the visible payoff of the Step 2 narrative chain.

---

## What changed from prior planning docs

- **First return to the `FunctionNode`+internal-`genai` pattern after the Step 5 agent node** — Step 6 deliberately is *not* a second `LlmAgent` node. Copy-gen is bounded LLM-at-the-node (Steps 2/4 category).
- **`event_id`-based signature, reading persisted queue from Mongo** — supersedes the stub's `(queue, operator_notes)` and the reframe's `(queue_items)` framing. Consistent with `score_assets_with_vision(event_id)` and D-022 (queue persisted on assets, re-renderable).
- **Redraft deferred to Step 7** — the stub's `operator_notes` is reserved but unused; the redraft branch lands with the HITL loop that defines its payload. (Reframe/spec describe redraft as part of this capability; this plan scopes its *implementation* to Step 7.)
- **No new model env var** — reuse `GEMINI_MODEL` (flash-lite), the `build_event_context` precedent; a flash draft var is a contingency, not a default.
- **Route → campaign-fields mapping made explicit** — resolves the 3-route → (product_type ∈ {poster,tshirt,null}, platform_target ∈ {shopify,printful,social}) wrinkle the schemas leave implicit.
- **Eval is single-tier (mocked CI gate) + an optional non-gating grounding probe** — opposite emphasis from Step 5, because the judgment is not the claim here; the demo's copy-grounding claim is checked as a deliberate quality probe, not a merge gate.

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

Doc-only; implementation must not contradict the spec it is written against. Per CLAUDE.md, every `docs/specs/` change needs a `tracking.md` D-entry. Step 6's housekeeping is **light** — the `campaigns`/`approvals` schemas and the `submit_campaign_for_review` wrapper are already documented (Step 5 / pre-existing); the edits mostly *confirm conventions* and record decisions.

1. **New D-entry (D-030): `draft_campaigns_for_queue` as a `FunctionNode` + copy-generation mechanics** (`tracking.md`). Captures: (a) `FunctionNode` + internal `genai` per-item copy gen (Steps 2/4 pattern, **not** a second `LlmAgent` node — `02-architecture.md`:373); (b) reuse `GEMINI_MODEL` (no `GEMINI_DRAFT_MODEL` by default — `build_event_context` precedent; model-default discipline); (c) route → `(product_type, platform_target)` mapping + the Step 7 execution-consistency coupling + `printful` reserved for enterprise multi-route; (d) status `scored → campaign_draft_created` is Step 6's transition (reconciles Step 5's deferral, D-029); (e) **redraft deferred to Step 7** — `operator_notes` reserved; (f) MVP one-campaign-per-asset; (g) per-item internal iteration (not batched) for grounding isolation; (h) **zero *surfaced* assets is valid-degenerate (empty result), not a precondition failure** — only missing event/narrative/scored-assets raise (a "call propose_review_queue first" message would misfire under the graph order); (i) the copy LLM consumes Step 4's **derived signals** (`detected_subjects` as an identity/commercial signal, `scores`) + the narrative, **not the raw image** (MVP cost choice); (j) **grounding granularity = event-narrative + identity, not photographed-action** (meets the spec's bar; action-dependent shots curated out via `demo-corpus.md`); (k) **post-demo/enterprise trajectory** (consolidated in § Enterprise trajectory): the MVP narrative is bounded *upstream* of Step 6 — its significance is operator-framed (`outcome_type` parsed from chat, not derived), its facts seeded, its `player_context` retrieval a plain `find` (not semantic RAG); enterprise depth is two orthogonal axes — Axis 1 richer factual/significance substrate (live/semantic RAG shifting the angle from *echo* to *derive*; payoff is **autonomy**, not just richness) and Axis 2 richer visual substrate (persisted Vision `scene_description`, **not** image-to-copy — preserving the perception/composition boundary); the MongoDB partner story is primarily that its **MCP is the trusted state/persistence backbone** for the whole agent (D-019, D-022 — the only data client, six collections, the resumable status machine), of which vector search is the most *visible* call but not the whole; a player/news vector index is an *additive* enterprise deepening (dual vector search: both *which images* and *which facts/significance*), not the partner story's foundation. Refines D-021, D-016 (narrative as copy substrate), D-022 (read persisted queue from Mongo); reconciles D-029's status-transition deferral.
2. **`docs/specs/02-architecture.md`** — add `GEMINI_MODEL` as the copy node's model in the model-env-var bullet (no new var); note the route → `(product_type, platform_target)` mapping in the `draft_campaigns_for_queue` MCP call section; graph diagram already shows `draft_campaigns_for_queue (FunctionNode)` (no change). Note the bundled write is three sequential MCP calls (no transaction) for MVP.
3. **`docs/db-wrapper-inventory.md`** — confirm `submit_campaign_for_review(campaign) -> {campaign_id, approval_id}` (already listed; drop any `reviewer_notes` input from the signature — approvals are created `pending` with empty notes).
4. **`docs/safety-measures.md`** — confirm the copy node carries `max_output_tokens` (per-item, sized for one headline+caption+hashtags) per the Gap 2 spend bound.
5. **`docs/specs/01-requirements.md` § `draft_campaigns_for_queue`** — one sentence confirming the redraft *implementation* lands in Step 7 (the capability surface reserves it; this branch implements first-pass drafting).

Sequence on this branch: (1) housekeeping commit (items 1–5, doc-only) → (2) plan + tasks gates → (3) implementation per task order → (4) Tier-1 trace eval (CI gate) → (5) merge to `main` with the updated "Next action" in `CLAUDE.md`.
