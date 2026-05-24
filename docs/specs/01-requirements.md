# 01 — Requirements: Functional Specification

## Hackathon Non-Negotiables

| Requirement | Specification |
|-------------|--------------|
| LLM | Gemini (any version via Agent Platform) — required |
| Partner MCP | MongoDB Atlas MCP — must be load-bearing, not cosmetic |
| Build environment | Google ADK v2.1 (code-only path, explicitly listed in spec as valid Agent Runtime) |
| Hosting | Cloud Run |
| Deliverables | Hosted project URL, public OSS repo with OSS license, ~3 min demo video, Devpost submission |
| Submission | Devpost form, MongoDB partner track selected |

## MVP Scope (Hard Limits — Do Not Expand)

- **Event type:** World Cup soccer only
- **Ecommerce:** Shopify (Partners dev store, GraphQL Admin API)
- **Print-on-demand:** Printful (poster, t-shirt — 2 product types max)
- **Social:** Simulated — agent creates complete post package, queued in MongoDB; no live platform API
- **Human approval:** Required before any execution step runs
- **Demo asset source:** Wikimedia Commons (CC-licensed soccer/sports photos, 20–50 image seed batch)

Scope creep is the primary timeline risk. Adding a second social platform, ecommerce system, or event type is not permitted without explicit user decision.

---

## MVP Assumptions

These are explicit simplifying decisions made for the hackathon demo. Each one is defensible in a judge conversation: *"This is the MVP; the enterprise path is X."* Do not treat them as oversights — they are deliberate scope constraints.

### Asset routing: one destination per image

Each asset is assigned exactly one `product_route`. Routing is mutually exclusive:

| Route | What it means |
|---|---|
| `poster` | Print-ready poster; listed on Shopify, fulfilled via Printful |
| `tshirt` | Print-ready t-shirt; listed on Shopify, fulfilled via Printful |
| `social_only` | Digital post package only; no physical product created |
| `null` | Asset did not meet threshold for any route; no action taken |

An asset with high scores on both `merch_score` and `social_score` is routed to `poster` — the higher-value commercial output wins. It is not simultaneously posted to social.

**Enterprise path:** multi-route (e.g. poster + social post in parallel); one campaign document per route per asset.

### Channel responsibility

| Channel | Responsibility | Implementation |
|---|---|---|
| Shopify | Product listing, storefront, sales transaction | GraphQL Admin API — creates product draft |
| Printful | Production and fulfillment of poster and t-shirt | REST API — async mockup → fulfillment on order |
| Social | Post package creation and scheduling | Simulated — full post package written to MongoDB with `status: "queued"` |

Shopify and Printful are always paired for physical products: Shopify owns the sale, Printful owns the production. In the demo, mockup generation is initiated by the agent; fulfillment would be triggered by Shopify's order webhook in a production deployment.

### Performance metrics: schema and semantics

The `performance` collection records post-execution outcomes. For the MVP:

**Time window:** rolling 7 days from `published_at`. All metrics represent cumulative totals within that window. The `window_days` field is stored on each document for traceability.

**Channel breakdown:** metrics are split by channel, not aggregated into a single revenue figure.

```json
{
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
  "window_days": 7
}
```

`shopify.revenue_usd` is gross order value (pre-fulfillment-cost). `printful.units_fulfilled` tracks production completions, not orders — these lag by 1–3 days in production. For the demo, both are written simultaneously as synthetic values.

**Enterprise path:** per-SKU attribution, multiple time windows (24h spike vs. 7-day long tail), net revenue after Printful fulfillment cost, cohort comparisons across events.

### What this system does not track (MVP)

- Refunds or order cancellations
- Printful fulfillment cost or margin
- Click-through rate from social post to Shopify product
- Return on ad spend
- Any metric requiring a live social platform API

### Routing strategy: exploitation with random exploration budget

The MVP uses similarity-based prioritization for the main approval queue, with an explicit 10% random exploration budget routed to a parallel **discovery queue**.

**Main queue (90%):** top-K assets by per-channel similarity score — the exploitation path. Assets that resemble past performers.

**Discovery queue (10%):** randomly sampled from remaining candidates regardless of similarity score. Random is the maximally honest form of exploration: it cannot structurally exclude any candidate by definition. Some discovery slots will go to mediocre images — that is the honest cost of genuine exploration.

The human operator reviews both queues and decides. The algorithm surfaces candidates; editorial judgment advances them.

**Why random for the MVP:** any filter — even "bottom-similarity tail" — reintroduces an exclusion criterion and recreates the structural problem at a smaller scale. Random makes no such claim.

**Expected to be tuned by customer and implementation:**

The right exploration strategy is a configuration decision, not a fixed design. Different operators have different discovery preferences:

- **Random (MVP default):** maximally honest; any candidate can surface regardless of how divergent
- **Low-similarity tail:** biased toward visually distinct outliers; for customers who specifically want to see the most divergent images
- **Diversity constraints:** force the top-K to include assets dissimilar from each other — broader coverage without full random selection
- **Novelty-scored queue:** score candidates explicitly for divergence from the existing corpus; algorithmically curated surprise for customers who want that signal

**Framing for judges:** *"We ship random as the default because it makes no assumptions about what novelty looks like. The right exploration strategy is a customer decision — some want genuine outliers, some want serendipitous discovery, some may want no exploration budget at all."*

---

## Non-Goals

- Not a chatbot or conversational assistant
- Not a general-purpose content generator
- Not an aesthetic image ranking tool
- Not a social media captioning tool in isolation
- Not a virality prediction system

---

## Agent Workflow — 8 Steps

### Step 1 — Ingestion
Operator uploads a batch of event photos. Agent receives:
- Image batch (paths or blob references)
- Event metadata: match result, teams, venue, kick-off time, outcome type (e.g., `upset_victory`, `expected_win`, `draw`)

Agent stores event record and bulk-inserts all images into MongoDB with `status: "ingested"`.

### Step 2 — Event Context Understanding
Agent retrieves the event record and queries historical events of the same outcome type. It aggregates past commercial performance for similar events to establish a baseline expectation.

Reasoning output: expected engagement profile, attention spike duration, likely product demand profile.

### Step 3 — Similarity-Grounded Routing
Agent embeds each candidate image using `gemini-embedding-2` (3072 dimensions) and runs vector search against the `assets` collection to find visually/semantically similar past assets with known per-channel performance data.

This is the **primary load-bearing MCP step**: the engine is per-channel image similarity to past performers. Images similar to past poster winners are candidates for poster routing; images similar to past social winners are candidates for social_only routing. Removing MongoDB removes this signal — routing degrades to pure LLM inference with no historical grounding.

### Step 4 — Operational Prioritization
Agent scores each asset across five image-level dimensions using Gemini Vision (see `00-overview.md` for definitions):
- `quality_score`, `emotional_score`, `social_score`, `merch_score`, `identity_score`

Event-level `timeliness` is read from the `events` document (computed at ingestion — not scored per image).

Agent groups top assets by product route using composite scores:
- **Poster candidate** — top-K by `merch_score` + `quality_score` weighted against event `timeliness`
- **T-shirt candidate** — top-K by `identity_score` + `quality_score` weighted against event `timeliness`
- **Social-only candidate** — top-K by `social_score` + `emotional_score`, where `merch_score` is below poster threshold

### Step 5 — Campaign Draft Creation
For each top asset, agent generates:
- Campaign draft: product specs, generated copy, platform target, timing recommendation
- Pushes all drafts into the approval queue with `status: "pending"`

### Step 6 — Human-in-the-Loop Review
Human operator reviews the approval queue. For each item:
- **Approved** → moves to execution
- **Rejected** → discarded, asset status updated
- **Edit requested** → draft returned for revision

No execution occurs until this gate is passed.

### Step 7 — Execution
For approved items, agent executes:
- **Shopify:** Creates product draft via GraphQL Admin API
- **Printful:** Initiates async mockup generation (`POST /mockups` → poll `GET /mockups/{task_id}`)
- **Social:** Writes complete post package to MongoDB with `status: "queued"` (simulated — no live API call)

### Step 8 — Feedback Loop
Post-execution, engagement and conversion metrics are written back to the `performance` collection. On subsequent runs, vector search in Step 3 returns richer signals because past assets now carry real performance data.

This is how the system improves over time without retraining.

---

## Demo Flow (Judge-Facing Narrative)

1. Upload 20–50 World Cup match photos + match metadata
2. Agent clusters and scores assets — show reasoning, not just scores
3. Show top-ranked assets with their score profiles and product routing
4. Agent generates campaign drafts for top candidates
5. Human approval queue appears — operator approves/rejects
6. Agent executes: Shopify draft created, Printful mockup initiated, social post queued
7. Show MongoDB state after execution — assets at `status: "published"`, campaigns logged

Total demo target: under 3 minutes. The story is operational velocity, not AI cleverness.

---

## Judging Criteria Alignment

| Criterion | How we address it |
|-----------|------------------|
| Technological Implementation | MongoDB MCP load-bearing across all 8 steps; Gemini for reasoning and embeddings; Google ADK v2.1 for stateful orchestration |
| Design | Clean approval UI; operational dashboard showing workflow state; score profiles visible |
| Potential Impact | Real economic problem — sports commerce monetization windows; scales to any live event |
| Quality of the Idea | Commercial operations framing differentiates from commodity content tools; grounded scoring via vector search |

---

## Success Metrics

- Time from event upload → approval queue populated (target: under 60 seconds for 50-image batch)
- Human approval rate on generated candidates
- Shopify draft creation success rate
- Printful mockup generation completion rate
- Demonstrability: can the full 8-step flow run end-to-end in a single demo session without errors
