# 02 — Architecture: System Design

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| LLM | Gemini (Vertex AI) | Required by hackathon — reasoning and vision |
| Embeddings | `gemini-embedding-2` (Vertex AI) | 3072 dimensions, multimodal (image + text) |
| Orchestration | Google ADK v2.1 | `LlmAgent` + `Workflow` graph for 8-step state machine |
| MCP integration | `McpToolset` (built into ADK) | Native ADK adapter; connects MongoDB MCP server as agent tools |
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
One document per live event. Written at Step 1, read at Step 2.

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
  "ingested_at": "2026-07-14T21:15:00Z"
}
```

`outcome_type` enum: `upset_victory`, `expected_win`, `draw`, `extra_time_win`

### `assets`
One document per image. Central state document — updated at every step.

```json
{
  "asset_id": "uuid",
  "event_id": "wc2026-match-42",
  "content_url": "gs://bucket/images/img_0042.jpg",
  "status": "ingested | scored | campaign_draft_created | executing | published | rejected",
  "product_route": "poster | tshirt | social_only | null",
  "embedding": [/* 3072-dim vector */],
  "scores": {
    "emotional_score": 0.87,
    "merch_score": 0.72,
    "social_score": 0.91,
    "identity_score": 0.68,
    "timeliness_score": 0.95
  },
  "similar_assets": ["asset_id_1", "asset_id_2"],
  "campaign_id": "uuid | null",
  "published_urls": {},
  "upload_date": "...",
  "scored_at": "...",
  "published_at": "..."
}
```

### `campaigns`
One document per asset-campaign pairing. Written at Step 5.

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
  "created_at": "..."
}
```

### `approvals`
Approval queue. Written at Step 5, updated by human at Step 6.

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
Post-execution engagement and conversion data. Written at Step 8. Feeds vector search scoring in future runs.

```json
{
  "performance_id": "uuid",
  "asset_id": "uuid",
  "campaign_id": "uuid",
  "event_id": "wc2026-match-42",
  "metrics": {
    "shopify_views": 0,
    "shopify_conversions": 0,
    "social_impressions": 0,
    "social_saves": 0,
    "revenue_usd": 0.00
  },
  "recorded_at": "..."
}
```

---

## Full MongoDB MCP Call List

### Step 1 — Ingestion
```
events.insertOne          → store event metadata
assets.insertMany         → bulk-insert all images, status: "ingested"
```

### Step 2 — Event Context Understanding
```
events.findOne            → retrieve this event's record
events.find               → find past events with same outcome_type
performance.aggregate     → aggregate historical conversion stats for this event type
```

### Step 3 — Commercial Signal Detection ← primary load-bearing step
```
assets.vectorSearch       → embed candidate image with gemini-embedding-2;
                            find visually similar past assets with known scores
```
Removing this call removes the evidential grounding for all scoring decisions.

### Step 4 — Operational Prioritization
```
assets.updateMany         → write score fields to each asset document
assets.aggregate          → group top assets by product_route
assets.updateMany         → set status: "scored", assign product_route
```

### Step 5 — Campaign Draft Creation
```
campaigns.insertOne       → per top asset: campaign draft with copy, specs, platform target
assets.updateOne          → set status: "campaign_draft_created"
approvals.insertMany      → push all drafts to queue, status: "pending"
```

### Step 6 — Human-in-the-Loop Review
```
approvals.find            → { status: "pending" } — fetch queue for display
approvals.updateOne       → record human decision (approved / rejected / edit_requested)
assets.updateOne          → sync status back to asset document
```

### Step 7 — Execution
```
approvals.find            → { status: "approved" } — fetch approved items
assets.updateOne          → set status: "executing"
[external: Shopify GraphQL, Printful REST]
assets.updateOne          → set status: "published", write platform URLs + timestamps
campaigns.updateOne       → record execution outcome
```

### Step 8 — Feedback Loop
```
performance.insertMany    → store engagement + conversion metrics
assets.aggregate          → find assets similar to best performers (informs future runs)
```

---

## External Integrations

### Shopify (GraphQL Admin API)
- **Account:** Shopify Partners dev store (free, unlimited)
- **API:** GraphQL Admin API — REST deprecated for products as of 2024-04
- **Scope needed:** `products`, `draft_orders`
- **Operations:** Create product, create draft order, update product status
- **Auth:** Admin API access token from Partners dashboard

### Printful (REST API)
- **Account:** Free; register at developers.printful.com
- **Auth:** Bearer token (Private Token for personal use)
- **Mockup flow (async):**
  1. `GET /products/variant/{id}/printfiles` — get print file specs for variant
  2. `POST /mockups` — submit image + variant → returns `task_id`
  3. `GET /mockups/{task_id}` — poll until `status: "completed"`; returns mockup URLs
- **ADK note:** Mockup polling maps to an ADK retry loop via `LongRunningFunctionTool`

### Social (Simulated)
- No live API. Agent writes a complete post package to MongoDB:
  - Image reference, caption, hashtags, optimal posting time, platform target
  - `status: "queued"` after human approval
- Rationale: Instagram requires Meta app review for production publishing; X/Twitter API is paywalled. Demo value is in orchestration, not live pixel delivery.

---

## ADK Agent Architecture

The 8-step workflow is implemented as an ADK `LlmAgent` with `LongRunningFunctionTool` for the human approval gate.

```
ingest → contextualize → score → prioritize → draft_campaigns →
  human_review [LongRunningFunctionTool — suspends] →
    approved → execute → record_performance → END
    rejected → END
    edit_requested → draft_campaigns (loop back)
```

Key ADK primitives used:
- **`LongRunningFunctionTool`** at `human_review` — returns `None` to suspend; runner emits `long_running_tool_ids`; resumes when caller sends `FunctionResponse` with matching `id`
- **`McpToolset(StdioConnectionParams(...))`** — connects MongoDB MCP server (`npx mongodb-mcp-server`) as native ADK tools; discovered and proxied automatically
- **`InMemorySessionService`** for local dev; swap to persistent session service for Cloud Run
- **State persistence** via MongoDB `assets` collection — every step writes status before returning so workflow is resumable across ADK sessions
- **Retry logic** in execute step for Printful async mockup polling (`POST /mockups` → poll `GET /mockups/{task_id}`)
- **Model:** `gemini-2.5-flash-lite` (confirmed working; `gemini-2.0-flash` deprecated for new API users)

Spike code at `spike/adk_hitl_test.py` — confirmed PASS on both HITL checks (2026-05-23).

---

## Hard Constraints

These must not be changed without explicit user decision:

1. **Do not simplify the 8-step workflow.** Do not merge steps or skip steps to reduce complexity. Each step exists for a reason documented in `01-requirements.md`.
2. **MongoDB is the partner MCP.** Do not substitute Elastic, Pinecone, or any other vector store.
3. **Gemini is the LLM backbone.** Do not substitute OpenAI, Anthropic, or any non-GCP model.
4. **`gemini-embedding-2` is the embedding model.** Do not substitute Voyage AI or any non-GCP embedding provider.
5. **Google ADK v2.1 is the orchestration layer.** Do not substitute LangGraph or Agent Builder without updating D-005 and the architecture spec. LangGraph is the documented fallback if ADK hits blockers.
6. **Social posting is simulated.** Do not wire a live Instagram, X/Twitter, or Buffer API.
7. **Do not rewrite tests to make them pass.** Fix the underlying implementation.
8. **Do not expand MVP scope** (additional event types, platforms, or product types) without explicit user approval.
