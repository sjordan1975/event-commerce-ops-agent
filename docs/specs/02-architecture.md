# 02 — Architecture: System Design

> **Updated for D-021** (2026-05-26) — the agent is reframed as **strategist composing 9 capabilities** with queue assembly as the one strategic decision. The pre-pivot "8-step workflow" framing is superseded. Sections updated: tech stack notes, MongoDB collection intros (capability references replace step references), MongoDB MCP call list (reorganized by capability), ADK Agent Architecture (workflow diagram replaced with capability composition framing), Hard Constraint #1. Sections unchanged: collection JSON schemas, external integrations, all other hard constraints. Full design rationale: `docs/strategic-agent-reframe.md`; D-021 in `tracking.md`.
>
> **Updated for D-022** (2026-05-27) — `build_event_context` persists the LLM-composed `EventNarrative` onto the producing `events` document (new `event_narrative` field). The `events` JSON example and the `build_event_context` MCP call list reflect the new write. Full rationale: `tracking.md` D-022; design context: `docs/plans/step-2-context.md` § "Persistence: `event_narrative` field on `events`".

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| LLM | Gemini (Vertex AI) | Required by hackathon — reasoning and vision |
| Embeddings | `gemini-embedding-2` (Vertex AI) | 3072 dimensions, multimodal (image + text) |
| Orchestration | Google ADK v2.1 | Single `LlmAgent` composing 9 capability tools; `LongRunningFunctionTool` at the HITL gate. No `Workflow` graph — the agent loops calling tools until terminal text (see `docs/agentic-model.md`) |
| MCP integration | `McpToolset` (built into ADK) | Native ADK adapter; used by domain wrappers as a programmatic client (D-019) — not registered in `agent.tools` |
| Database / state | MongoDB Atlas | Partner MCP track; all state, queues, vector search, memory |
| Ecommerce | Shopify GraphQL Admin API | Partners dev store (free); products + draft orders |
| Print-on-demand | Printful REST API | Async mockup generation; free account |
| Social | Simulated | Post package written to MongoDB; no live platform API |
| Hosting | Cloud Run | Python agent backend; listed in hackathon spec for custom backends |
| Credentials | GCP Secret Manager | API keys for Shopify, Printful; Vertex AI uses ADC |
| Demo assets | Wikimedia Commons | 20–50 CC-licensed soccer/sports photos; static seed batch |

---

## MongoDB Collections

### `events`
One document per live event. Written by `ingest_event_batch`; read by `build_event_context` and downstream capabilities that need event metadata.

```json
{
  "event_id": "wc2026-match-42",
  "name": "Argentina vs France",
  "home_team": "Argentina",
  "away_team": "France",
  "location": "MetLife Stadium",
  "start_date": "2026-07-14T19:00:00Z",
  "final_score": "Argentina 3–2 France",
  "outcome_type": "upset_victory",
  "timeliness": 0.95,
  "ingested_at": "2026-07-14T21:15:00Z",
  "event_narrative": null
}
```

`event_narrative` — populated by `build_event_context` once the LLM composes the typed narrative (per D-022). Shape: `EventNarrative` (`narrative_angle`, `key_figures[]`, `commercial_timing`, `historical_baseline`); `null` between ingestion and context build. See `docs/plans/step-2-context.md` § "The `EventNarrative` model (D-016 contract)" for full type definition.

`outcome_type` enum: `upset_victory`, `expected_win`, `draw`, `extra_time_win`

`timeliness` — computed once at ingestion; not scored per image by Gemini. Formula: `base_score × 0.5^(hours_since_kickoff / 4)`.

| `outcome_type` | base score |
|---|---|
| `upset_victory` | 0.95 |
| `extra_time_win` | 0.85 |
| `expected_win` | 0.60 |
| `draw` | 0.40 |

### `assets`
One document per image. Central state document — touched by nearly every capability (ingestion → scoring → queue assignment → campaign linkage → execution → published URLs).

```json
{
  "asset_id": "uuid",
  "event_id": "wc2026-match-42",
  "content_url": "gs://bucket/images/img_0042.jpg",
  "status": "ingested | scored | campaign_draft_created | executing | published | rejected",
  "product_route": "poster | tshirt | social_only | null",
  "queue_type": "exploitation | discovery | null",
  "queue_rank": "1-based rank within the asset's queue half | null (set by propose_review_queue, D-029)",
  "queue_rationale": "one-sentence operator-facing reasoning | null (set by propose_review_queue, D-029)",
  "embedding": [/* 3072-dim vector */],
  "scores": { /* AssetScores: quality_score, merch_score, emotional_score, social_score, identity_score — all [0,1]; D-013, D-017, D-027 */ },
  "detected_subjects": ["Lionel Messi"],
  "similar_assets": ["asset_id_1", "asset_id_2"],
  "campaign_id": "uuid | null",
  "published_urls": {
    "shopify": {
      "product_id": "gid://shopify/Product/8842301234",
      "product_url": "https://demo-store.myshopify.com/products/wc2026-poster-abc"
    },
    "printful": {
      "task_id": "8847291",
      "mockup_url": "https://printful.com/mockups/rendered/poster_abc123.jpg"
    },
    "social": {
      "status": "queued",
      "queued_at": "2026-07-14T22:05:00Z"
    }
  },
  "upload_date": "..."
}
```

`published_urls` is populated by `execute_approved_campaigns`. Only the keys relevant to `product_route` are written — poster/tshirt assets get `shopify` + `printful`; social_only assets get `social`. The Printful `mockup_url` is the rendered product image — the primary visual artifact of the Printful integration in the demo.

### `campaigns`
One document per asset-campaign pairing. Written by `draft_campaigns_for_queue`; execution fields updated by `execute_approved_campaigns`.

```json
{
  "campaign_id": "uuid",
  "asset_id": "uuid",
  "event_id": "wc2026-match-42",
  "product_type": "poster | tshirt",
  "generated_copy": {
    "headline": "...",
    "caption": "...",
    "hashtags": ["#WorldCup2026", "#ArgentinaVsFrance"]
  },
  "platform_target": "shopify | printful | social",
  "timing_recommendation": "2026-07-14T22:00:00Z",
  "status": "draft | approved | rejected | executed",
  "created_at": "...",
  "execution": {
    "shopify_product_id": "gid://shopify/Product/8842301234",
    "printful_task_id": "8847291",
    "printful_mockup_url": "https://printful.com/mockups/rendered/poster_abc123.jpg",
    "executed_at": "2026-07-14T22:05:00Z"
  }
}
```

`execution` is written by `execute_approved_campaigns` when the campaign is dispatched. It is `null` until execution completes. For social_only campaigns `shopify_product_id`, `printful_task_id`, and `printful_mockup_url` are omitted. The `printful_mockup_url` is the key demo artifact — a rendered image of the product shown in the approval and execution UI.

### `approvals`
Approval queue. Written by `draft_campaigns_for_queue`; updated by the human via `request_human_approval`.

```json
{
  "approval_id": "uuid",
  "campaign_id": "uuid",
  "asset_id": "uuid",
  "status": "pending | approved | rejected | edit_requested",
  "reviewer_notes": "...",
  "created_at": "...",
  "decided_at": "..."
}
```

### `performance`
Post-execution engagement and conversion data. Written by `record_outcomes`. Feeds vector search in `find_similar_assets` on future runs — past assets carry real performance data.

```json
{
  "performance_id": "uuid",
  "asset_id": "uuid",
  "campaign_id": "uuid",
  "event_id": "wc2026-match-42",
  "metrics": {
    "shopify": {
      "views": 0,
      "orders": 0,
      "revenue_usd": 0.00
    },
    "printful": {
      "units_fulfilled": 0
    },
    "social": {
      "impressions": 0,
      "saves": 0
    }
  },
  "window_days": 7,
  "recorded_at": "..."
}
```

Metrics represent cumulative totals over a rolling 7-day window from publish time (recorded as `window_start`, anchored on the campaign's `execution.executed_at`; stored as `window_days: 7`).
Channel population follows `product_route`: poster/tshirt assets populate `shopify` + `printful`; social_only assets populate `social` only.

**MVP write shape (D-032):** `record_outcomes` writes a **provenance record** with `metrics: null` and a `metrics_status: "pending_sync"` discriminator — the zeroed `metrics` object shown above is the **measured** shape the external sync populates later (enterprise path), not what the coda writes. The provenance doc also carries `channels` (awaiting measurement, derived from `product_route`) and `window_start` (publish time). **Consumers must honor the discriminator:** `aggregate_performance_for_events` (the Step-2 baseline reader) excludes `metrics_status == "pending_sync"` so pending rows never dilute the baseline — any future reader of `performance` must do the same.

### `player_context`
Static reference corpus. Seeded at onboarding; read by `build_event_context` to ground the event narrative.

```json
{
  "player_id": "uuid",
  "name": "Lionel Messi",
  "nationality": "Argentina",
  "team": "Argentina",
  "position": "Forward",
  "notable_facts": [
    "5th World Cup appearance",
    "2022 World Cup winner",
    "All-time leading scorer in World Cup finals"
  ],
  "career_milestones": "Widely regarded as final World Cup; 2022 champion",
  "commercial_signal": "high"
}
```

`commercial_signal` — editorial pre-rating of how much a player's presence lifts the commercial value of an image: `high | medium | low`. Set at seed time; not computed by the agent.

Lookup is by team name match against `events.home_team` / `events.away_team` — plain find, no vector search. Returns all players for both squads; LLM selects the narratively significant ones.

---

## Atlas Vector Search indexes

One Atlas Vector Search index defined on the `assets` collection. Used by `find_similar_assets` (capability 3) — see D-025 for the Step 3 architectural choices.

| Index | Collection | Field path | Dimensions | Similarity | Type |
|---|---|---|---|---|---|
| `assets_embedding_index` | `assets` | `embedding` | 3072 | `cosine` | `vectorSearch` |

Dimension matches `gemini-embedding-2` output (D-006). Cosine is the standard for Gemini multimodal embeddings; cosine ≈ dotProduct on L2-normalized outputs. Index name is overridable via the `VECTOR_INDEX_NAME` env var so eval and live deployments can use different indexes if needed.

The index also declares **`event_id` as a `filter` field** (D-034). `find_similar_assets` excludes the query asset's own event *inside* `$vectorSearch` (a pre-filter: `filter: {event_id: {$ne: <current>}}`), so the `top_k` results are drawn from *other* events directly. A post-`$vectorSearch` `$match` cannot do this correctly — it runs after `limit`, so same-event neighbors (which dominate the nearest matches) consume all `top_k` slots and are then discarded, returning zero.

**Provisioning:** one-time idempotent setup via `scripts/setup_vector_index.py`. Atlas index creation is asynchronous (~minutes); not done at runtime. Re-running the script no-ops if the index already exists.

---

## Full MongoDB MCP Call List

Organized by capability. Per D-019, the agent does not call MongoDB directly — domain wrappers under each capability call `MongoMCPClient` (which wraps `McpToolset`) internally. The MCP operations below are what runs *inside* each capability.

### `ingest_event_batch`
```
events.insertOne          → store event metadata (with computed timeliness)
assets.insertMany         → bulk-insert all images, status: "ingested"
```

### `build_event_context`
```
events.findOne            → retrieve this event's record
events.find               → find past events with same outcome_type
performance.aggregate     → aggregate historical conversion stats for this event type
player_context.find       → retrieve squad members for both teams (plain name match, no vector search)
events.update-many        → persist the LLM-composed event_narrative onto the event document (per D-022)
```
LLM output: structured event narrative (narrative angle, key figures with grounded facts, commercial timing, historical baseline). Persisted onto the producing `events` document under `event_narrative` (per D-022) and returned to agent state. Read by `propose_review_queue` as a hard precondition (capability 5) and by `draft_campaigns_for_queue` as copy substrate (capability 6 per D-016). Player context is retrieved here, once per event batch — not once per asset.

### `find_similar_assets` ← primary load-bearing MCP step
```
(per asset in the event, if asset.embedding is None:)
[external] Vertex AI gemini-embedding-2 → compute 3072-dim image embedding
assets.update-many        → persist embedding (permanent; idempotent skip on re-run)

(per asset in the event:)
assets.aggregate          → $vectorSearch on assets_embedding_index (path: embedding,
                            queryVector: asset.embedding, numCandidates: 10 × top_k,
                            limit: top_k) → $match excluding current event_id →
                            $project asset_id, event_id, product_route, scores,
                            similarity ($meta: vectorSearchScore)
assets.update-many        → persist neighbor asset_ids onto current asset (similar_assets)
```
Top-K defaults to 5 (D-025). Removing the `$vectorSearch` call removes the per-channel similarity signal — routing degrades to pure LLM inference. The current event's assets get embedded and persisted, so today's batch becomes tomorrow's similarity corpus (the feedback-loop seed).

### `score_assets_with_vision`
```
(per asset in the event, if asset.scores is None:)
[external] Gemini Vision (gemini-2.5-flash via google.genai, structured output) → AssetScores + detected_subjects
assets.update-many        → set scores (typed AssetScores per D-027), detected_subjects (list[str] per D-026),
                            and status: "scored" — bundled write
```
Per D-017: scores split into technical fitness (`quality_score`, `merch_score`) + commercial signal (`emotional_score`, `social_score`, `identity_score`). Per D-026: `detected_subjects` carries the identity signal forward for Step 5 to compose against narrative `key_figures`. Per D-028: Vision model defaults to `gemini-2.5-flash` (not flash-lite — judgment density + hallucination surface).

### `propose_review_queue` ← the one strategic decision
Three workflow nodes (D-029): a mechanical split, the strategic `LlmAgent` node, and a mechanical persist. The `LlmAgent` node does no MongoDB I/O — the flanking `FunctionNode`s do.
```
prepare_queue_candidates (FunctionNode)
  (consumes similarity_results + scored_assets from state; PreconditionError if either/narrative missing)
  → split by QUEUE_EXPLOITATION_SIMILARITY_CUTOFF into exploitation (carry inferred_route) + discovery pools

propose_review_queue (LlmAgent, mode='single_turn')
  → orders exploitation by narrative fit + identity (D-026) + quality gate (D-017); selects discovery subset;
    emits ReviewQueue (output_schema) with per-item rationale + strategy_summary → state["review_queue"]

persist_review_queue (FunctionNode)
  assets.updateMany  → per surfaced item: set queue_type ("exploitation" | "discovery"), product_route
                       (mechanical inferred_route for exploitation per D-015; LLM choice for discovery),
                       queue_rank, queue_rationale. Does NOT change status (stays "scored").
```
Per D-021/D-029, the discovery-half selection is agent-driven (not random per D-015's MVP default); each surfaced item carries a one-sentence rationale the operator can read. Preconditions are enforced in `prepare_queue_candidates` (hard-refuse via `PreconditionError` if event, scores, similarity results, or narrative are missing). Persist is defensive — cross-assigned/invented `asset_id`s are recorded, not crashed on.

### `draft_campaigns_for_queue`
```
campaigns.insertOne       → per queued asset: campaign draft with copy, specs, platform target
assets.updateOne          → set status: "campaign_draft_created" + link campaign_id
approvals.insertMany      → push all drafts to queue, status: "pending"
```
Realized as a `FunctionNode` (D-030), per-item internal `genai` copy generation on `GEMINI_MODEL`. The three writes are bundled as one logical domain operation (`submit_campaign_for_review`) — three sequential MCP calls, **not a transaction** (single-operator MVP). **Route → campaign fields** (D-030): `poster→(product_type=poster, platform_target=shopify)`, `tshirt→(tshirt, shopify)`, `social_only→(product_type=null, platform_target=social)`. `platform_target` is a display label — execution selects channels off `product_route` directly; `printful` is reserved for the enterprise multi-route path.

On a redraft cycle (operator `edit_requested`), called with the original queue + operator notes — overwrites the corresponding `campaigns` documents and recreates `approvals` entries. **Redraft is implemented in Step 7** (with the HITL loop that defines the `operator_notes` payload); Step 6 implements first-pass drafting and reserves the `operator_notes` parameter.

### `request_human_approval` (coordinator-side; D-031)
```
request_human_approval (LongRunningFunctionTool — the GATE; no decision writes):
  approvals.find          → { event_id, status: "pending" } — fetch queue for display
  → returns the grouped display batch as the initial pending payload, then SUSPENDS.

[on the NEXT LLM turn, after the operator's FunctionResponse:]
apply_approval_decisions (FunctionTool — persists the per-item decisions list):
  approvals.updateOne     → record decision (approved / rejected / edit_requested) + reviewer_notes
  campaigns.updateOne     → cascade campaign status (approved/rejected; stays draft for edit)
  assets.updateOne        → cascade asset status (rejected on reject; else unchanged)
```
**Correction (D-031):** a `LongRunningFunctionTool` body does **not** re-run on resume — the operator's `FunctionResponse` is delivered to the coordinator LLM, not back into the function. So the gate cannot record decisions; a **separate `apply_approval_decisions` tool** does, on the next turn. `request_human_approval`, `apply_approval_decisions`, and `execute_approved_campaigns` are **coordinator `FunctionTool`s** (capabilities 7/8 are coordinator-plane — not workflow graph nodes). Operator decisions arrive as a per-item **list keyed by `approval_id`**.

### `execute_approved_campaigns` (coordinator-side; D-031)
```
approvals.find            → { event_id, status: "approved", execution: null } — fetch approved, not-yet-executed
assets.updateOne          → set status: "executing"
[external: Shopify GraphQL, Printful REST (mockup polling = INTERNAL async loop, not a LongRunningFunctionTool)]
assets.updateOne          → set status: "published", write platform URLs + timestamps
campaigns.updateOne       → record execution outcome (campaign status: "executed")
```
Channel selection is by `product_route` (poster/tshirt → shopify+printful; social_only → social). Failure is **retriable** (leaves `execution: null`, approval stays `approved`), not terminal. **MVP build:** the four external helpers are **stubbed at the seam** (canned payloads); live Shopify/Printful wiring is a demo-prep task (D-031). The redraft loop on `edit_requested` re-reads persisted `edit_requested` approvals and overwrites the campaign drafts (Step 7 implements it; reconciles D-030's deferral).

### `record_outcomes` (coordinator-side; D-032)
```
assets.find               → { event_id, status: "published" } — the published set (reuses get_assets_for_event)
campaigns.find            → by campaign_id — pull execution.executed_at (window anchor; reuses get_campaigns_by_ids)
performance.updateMany    → UPSERT one provenance row per published asset (key: asset_id+event_id);
                            metrics: null, metrics_status: "pending_sync" — NO fabricated metrics
```
**Thin honest coda (D-032):** a provenance write only — `metrics` are synced asynchronously by an external process over the 7-day window, not written here. **Upsert** (not `insertMany`) for idempotency — execution is retriable, so a re-run must not double-write. No LLM call, no external API call. The forward-looking `get_top_performers_by_channel` analytics aggregate (`performance aggregate` + `assets find`, "find best performers") is **deferred** (designed-not-built; enterprise/demo-prep).

---

## External Integrations

### Shopify (GraphQL Admin API)
- **Account:** Shopify Partners dev store (free, unlimited)
- **API:** GraphQL Admin API — REST deprecated for products as of 2024-04
- **Scope needed:** `products`, `draft_orders`
- **Operations:** Create product, create draft order, update product status
- **Auth:** Admin API access token from Partners dashboard

### Mockup + Shopify publish (D-036)
- Printful is not in the execution path.
- **Mockup generation:** Gemini image gen for t-shirts (blank shirt + design photo); source photo used directly for posters.
- **Shopify publish:** `stagedUploadsCreate` → multipart upload to GCS → `productCreate` → `productCreateMedia`. Product created as DRAFT with mockup as product image.
- **Preview mode:** no Shopify creds → mockup bytes stored in `src/mockup_store`, served at `GET /api/mockup/{asset_id}`.

### Social (Simulated)
- No live API. Agent writes a complete post package to MongoDB:
  - Image reference, caption, hashtags, optimal posting time, platform target
  - `status: "queued"` after human approval
- Rationale: Instagram requires Meta app review for production publishing; X/Twitter API is paywalled. Demo value is in orchestration, not live pixel delivery.

---

## ADK Agent Architecture (revised by D-024)

The system is a **coordinator `LlmAgent` over a `google.adk.workflow.Workflow` graph**. The coordinator (chat mode) owns the operator conversation, clarification, and HITL. The workflow (graph) owns deterministic capability execution and (from Step 5) hosts one `LlmAgent(mode='single_turn')` node for the strategic decision (`propose_review_queue`). The pre-D-024 single-`LlmAgent` free loop is gone — execution order is now enforced by graph edges, not by prompt + `PreconditionError`. Full loop semantics: `docs/agentic-model.md`. Implementation details + spike validation: `tracking.md` D-024 and `docs/spike-d023-findings.md`.

### Top-level composition

```text
Coordinator LlmAgent (mode='chat', gemini-2.5-flash)
├── sub_agent: clarify_event_metadata (LlmAgent, mode='task')   ← bidirectional clarification
├── tool: run_event_pipeline (FunctionTool)                     ← dispatches the workflow via sub-Runner
└── tool: request_human_approval (LongRunningFunctionTool)      ← HITL gate

Workflow (graph, name='event_pipeline', runs via sub-Runner from the dispatch tool)
  START
    │
    ▼
  ingest_event_batch (FunctionNode)
    │
    ▼
  build_event_context (FunctionNode)
    │
    ▼  [Step 3+]
  find_similar_assets (FunctionNode)         ← added in Step 3
    │
    ▼  [Step 4+]
  score_assets_with_vision (FunctionNode)    ← added in Step 4
    │
    ▼  [Step 5+]
  prepare_queue_candidates (FunctionNode)    ← mechanical: similarity-cutoff split (D-029)
    │
    ▼
  propose_review_queue (LlmAgent, mode='single_turn', GEMINI_QUEUE_MODEL=gemini-2.5-flash) ← the one strategic decision
    │
    ▼
  persist_review_queue (FunctionNode)        ← mechanical: write per-asset queue fields (D-029)
    │
    ▼  [Step 6+]
  draft_campaigns_for_queue (FunctionNode)   ← added in Step 6
    │
    ▼
  END

[coordinator picks up after END:]
  request_human_approval  → LongRunningFunctionTool, suspends
        ├─ all approved   ─→ execute_approved_campaigns (Step 7) ─→ record_outcomes (Step 8) ─→ terminal text
        ├─ any rejected   ─→ those items drop; subset proceeds to execute
        └─ edit_requested ─→ re-dispatch drafts capability with notes → request_human_approval (loop)
```

The workflow's order is **structurally enforced** by graph edges, not by prompts. The agent cannot skip a capability or invent one. Each step extends the workflow by adding nodes and edges via `src/capabilities/__init__.py:build_pipeline_graph()`; the agent shell (`src/agent.py`) does not change.

HITL approval + execution + outcomes (capabilities 7–9) live coordinator-side, not in the workflow. HITL suspension needs to halt the operator conversation, which is the coordinator's plane; execution and outcomes branch on operator decisions, which is also a coordinator concern.

### Key ADK primitives

- **Coordinator `LlmAgent`** (chat mode) — `event_commerce_ops_coordinator`, `gemini-2.5-flash`. Owns conversation, clarification, and HITL. Implementation: `src/agent.py:build_coordinator`.
- **`LlmAgent(mode='task')` sub-agent** — `clarify_event_metadata`. Auto-wrapped as `_TaskAgentTool` via `coordinator.sub_agents`. Multi-turn exchange validated in `spike/adk_workflow_hitl_spike.py`.
- **`google.adk.workflow.Workflow`** — the deterministic pipeline graph. `SequentialAgent` is deprecated in ADK v2.1; `Workflow` is the modern replacement. The graph is built by `src/capabilities/__init__.py:build_pipeline_graph()` and instantiated by `src/agent.py:build_workflow`.
- **`FunctionNode(func=fn, parameter_binding='state')`** — wraps each deterministic capability. Reads parameters from `ctx.state`; writes results back to `ctx.state` for downstream nodes. The function bodies in `src/capabilities/{ingest,context,...}.py` are unchanged from pre-D-024 form.
- **`run_event_pipeline` `FunctionTool` shim** — the coordinator dispatches the workflow by calling this tool. The shim creates a fresh `InMemorySessionService`, seeds session state with `{"images": ..., "event_metadata": ...}`, and runs a sub-`Runner(node=workflow)`. Returns the final state. `Workflow` extends `BaseNode`, not `BaseAgent`, so `AgentTool` cannot wrap it.
- **`LongRunningFunctionTool` at `request_human_approval`** — coordinator-side, not workflow-side. Returns `None` to suspend; runner emits `long_running_tool_ids`; resumes when caller sends `FunctionResponse` with matching `id`.
- **`McpToolset(StdioConnectionParams(...))`** — connects MongoDB MCP server (`npx mongodb-mcp-server`). Per D-019, owned by `src/db/client.py` as a programmatic client — not registered in `agent.tools`. Discovered tools are invoked by domain wrappers inside each capability via `MongoMCPClient.call(tool_name, args)`.
- **`InMemorySessionService`** for local dev; swap to persistent session service for Cloud Run.
- **State persistence** via MongoDB `assets` collection — most capabilities write `status` updates so the trajectory is resumable across ADK sessions.
- **Retry logic** internal to `execute_approved_campaigns` for Printful async mockup polling.
- **`PreconditionError`** — wrapper-level exception with self-correcting message format. Under D-024 the graph enforces order structurally; `PreconditionError` remains as defense-in-depth for direct capability calls (e.g., from unit tests). See `docs/strategic-agent-reframe.md` § Enforced vs. emergent.
- **Loop and spend bounds** — ADK's iteration cap and `max_output_tokens` are the operational safety bounds. Explicit values + cap on the `edit_requested` redraft loop are tracked in `docs/safety-measures.md`.
- **Model env vars (D-024 + D-028 + D-029):** `GEMINI_COORDINATOR_MODEL` (default `gemini-2.5-flash`) for the coordinator + task sub-agents; `GEMINI_MODEL` (default `gemini-2.5-flash-lite`) for general workflow nodes (the internal LLM call in `build_event_context`, and `draft_campaigns_for_queue`'s copy generation per D-030 — both grounded text-gen, no dedicated var); `GEMINI_VISION_MODEL` (default `gemini-2.5-flash`, D-028) for `score_assets_with_vision`; `GEMINI_QUEUE_MODEL` (default `gemini-2.5-flash`, D-029) for the strategic `propose_review_queue` node — the judgment-dense nodes default to flash, not flash-lite.

Spike code: `spike/adk_hitl_test.py` (HITL primitive — pre-D-024), `spike/adk_event_capture.py` (event trace classification), `spike/adk_workflow_hitl_spike.py` (D-024 validation — all three load-bearing primitives). Findings: `docs/spike-d023-findings.md`.

---

## UI Layer (D-033)

The operator console is a Next.js frontend backed by a thin FastAPI HTTP layer that wraps the ADK coordinator. Full UI design spec: `docs/plans/approval-ui-spec.md`.

The FastAPI backend also owns the **MCP connection lifecycle** (D-035): the MongoDB MCP session is established once at `lifespan` startup (not lazily per request), kept alive and reused, health-gated (fail fast when unavailable), and exposed via a health endpoint. Treating MCP as a persistent connection (database-pool model) rather than a per-request REST call is what keeps the load-bearing partner integration fast and the boot failures explicit. Design: `docs/plans/mcp-connection-lifecycle.md`.

### Directory layout

```text
src/                  ← Python agent
├── agent.py          ← coordinator LlmAgent + workflow graph + coordinator tools
├── capabilities/     ← one module per capability (ingest, context, similarity,
│                        scoring, queue, drafts, execution, outcomes)
├── db/               ← MongoDB wrapper modules (events, assets, campaigns,
│                        approvals, performance, player_context, client)
├── errors.py         ← PreconditionError and shared error types
├── images.py         ← local image proxy (serves assets to UI via /api/image)
├── mockup_store.py   ← in-process mockup byte store (preview mode, no Shopify creds)
├── models.py         ← Pydantic models for all MongoDB document shapes
├── prompt_loader.py  ← versioned prompt loader (PROMPT_VERSION env var)
├── sse.py            ← per-session SSE queue registry
└── timeliness.py     ← timeliness score computation

src/api/              ← FastAPI HTTP + SSE bridge
├── server.py         ← FastAPI app (app = FastAPI(...)), all endpoints
├── session_store.py  ← in-process session / runner store
├── index.html        ← minimal chat UI for headless testing
└── package.json      ← vendored mongodb-mcp-server binary (D-035)

prompts/v3/           ← active system prompts (v3, set by PROMPT_VERSION)
├── coordinator_system.md
├── clarification_system.md
├── build_event_context.md
├── score_asset_with_vision.md
├── propose_review_queue.md
└── draft_campaign_copy.md

tests/
├── conftest.py       ← shared fixtures and model builders
├── test_step_1.py … test_step_8.py  ← unit + scaffolding tests per capability
└── evals/            ← live LLM evals (Tier-2, require GOOGLE_API_KEY, run deliberately)

scripts/              ← provisioning and demo lifecycle
├── setup_mongodb.py  ← create collections and indexes
├── setup_vector_index.py
├── seed_mongodb.py   ← seed player_context and past-event corpus
├── seed_images.py
├── reset_atlas.py    ← demo reset between runs
├── capture_mcp_fixtures.py
└── smoke_shopify.py

ui/                   ← Next.js operator console
├── src/app/          ← App Router pages (layout.tsx, page.tsx)
├── src/components/   ← ActivityTimeline, AppShell, ApprovalBatch, AssetCard,
│                        ChatBar, ContentPane, EventDivider, EventHeader,
│                        EvidenceSection, McpHealthBadge, NoticeCard,
│                        ScoreBar, StreamingNotices
├── src/hooks/        ← usePipeline.ts
├── src/lib/          ← health-api.ts, live-api.ts, mock-api.ts, types.ts, utils.ts
├── src/mock/         ← event1.json, event2.json (mock-mode fixtures)
└── next.config.ts    ← dev proxy: /api/* → localhost:8000
```

### Two servers

| Server | Command | Port | Responsibility |
|--------|---------|------|---------------|
| Python API | `uvicorn src.api.server:app --reload` | 8000 | ADK coordinator, SSE stream, approval resumption |
| Next.js | `cd ui && npm run dev` | 3000 | Operator console UI |

In development, `next.config.ts` proxies all `/api/*` requests from port 3000 → port 8000 so the UI never references the backend port directly. In production on Cloud Run, the options are two separate services (recommended) or a single service that serves the Next.js static build from FastAPI.

### API surface

```
POST  /api/sessions
      body: { message: string }
      → { session_id: string }
      Starts a coordinator session, delivers the operator's kickoff message.

GET   /api/sessions/{session_id}/stream
      → SSE stream of agent events (see event types below)

POST  /api/sessions/{session_id}/messages
      body: { message: string }
      → 200 OK
      Delivers a follow-up message (clarification exchange).

POST  /api/approvals/{approval_id}
      body: [{ asset_id, decision: "approved"|"rejected"|"edit_requested", notes? }]
      → 200 OK
      Delivers HITL decisions; triggers LongRunningFunctionTool resume.
```

### SSE event types

The `/stream` endpoint emits a sequence of typed events the UI renders in real time:

```
capability_started       { capability, event_id }
capability_completed     { capability, result_summary, event_id }
coordinator_message      { text, role: "coordinator"|"operator" }
approval_ready           { approval_id, items: ApprovalItem[], event_id }
execution_evidence       { shopify_products, social_posts, event_id }
mockup_resolved          { asset_id, mockup_url }          ← async, arrives after execution_evidence
atlas_state              { collection_counts }
pipeline_complete        { event_id }
```

### HITL resumption across the HTTP boundary

The `LongRunningFunctionTool` at `request_human_approval` suspends the coordinator runner. The runner holds an open async task; the session state is live in the session service. When the operator POSTs decisions to `/api/approvals/{approval_id}`, `session_bridge.py` calls `apply_approval_decisions` via the existing ADK pattern, which writes the per-item decisions to MongoDB and delivers a `FunctionResponse` back to the suspended runner. The runner resumes the coordinator, which reads the persisted decisions and calls `execute_approved_campaigns`.

With `InMemorySessionService` this is straightforward — session is in process memory. **The demo video runs on localhost; `InMemorySessionService` is sufficient.** Batch images are pre-staged at `/tmp/wc-final/` (localhost) and referenced by that path in the operator's kickoff message. On Cloud Run, images must be pre-uploaded to GCS; the operator uses a `gs://` path instead, `ingest_event_batch` enumerates the bucket, and `content_url` stores `gs://` URIs — which Vertex AI (embeddings + Vision) reads natively without any additional auth step.

For Cloud Run: the `LongRunningFunctionTool` suspension is a live async coroutine held inside `runner.run_async()` — it is process-local, not a checkpoint in the session service. `DatabaseSessionService` persists conversation history across restarts but does **not** solve cross-instance HITL resumption (the suspended coroutine cannot be handed to a different process). The pragmatic solution for the hackathon submission is single-instance Cloud Run (`--min-instances=1 --max-instances=1`): one process, always warm, session stays in memory. `DatabaseSessionService` (MongoDB-backed) is still worth wiring for conversation history persistence and honest architecture framing, but it does not change HITL resumption behavior. Tracked in `docs/plans/delivery-roadmap.md` § Track 4.

### Phase A / Phase B

**Phase A (mock-first):** `src/api/` does not exist yet. The Next.js app runs standalone. All API calls are intercepted by `ui/src/lib/mock-api.ts`, which reads from JSON fixtures in `ui/src/mock/` and simulates event timing with delays. No Python server needed.

**Phase B (wire-up):** Replace the mock API layer with real `fetch` + `EventSource` calls to the Python server. The UI components are unchanged — only the data source swaps.

---

## Hard Constraints

These must not be changed without explicit user decision:

1. **Do not remove capabilities or collapse the queue-assembly decision into a heuristic.** The 9 capabilities each exist for a reason documented in `01-requirements.md`; `propose_review_queue` is the one strategic decision and may not be replaced with deterministic ranking. (Revised per D-021 — was previously *"Do not simplify the 8-step workflow."*)
2. **MongoDB is the partner MCP.** Do not substitute Elastic, Pinecone, or any other vector store.
3. **Gemini is the LLM backbone.** Do not substitute OpenAI, Anthropic, or any non-GCP model.
4. **`gemini-embedding-2` is the embedding model.** Do not substitute Voyage AI or any non-GCP embedding provider.
5. **Google ADK v2.1 is the orchestration layer.** Do not substitute LangGraph or Agent Builder without updating D-005 and the architecture spec. LangGraph is the documented fallback if ADK hits blockers.
6. **Social posting is simulated.** Do not wire a live Instagram, X/Twitter, or Buffer API.
7. **Do not rewrite tests to make them pass.** Fix the underlying implementation.
8. **Do not expand MVP scope** (additional event types, platforms, or product types) without explicit user approval.
