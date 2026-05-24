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

### Step 3 — Commercial Signal Detection
Agent embeds each candidate image using `gemini-embedding-2` (3072 dimensions) and runs vector search against the `assets` collection to find visually/semantically similar past assets with known commercial performance scores.

This is the **primary load-bearing MCP step**: scoring is grounded in historical performance data, not pure LLM inference. Removing MongoDB here breaks the agent's ability to reason from evidence.

### Step 4 — Operational Prioritization
Agent scores each asset across five dimensions (see `00-overview.md` for score definitions):
- `emotional_score`, `merch_score`, `social_score`, `identity_score`, `timeliness_score`

Agent groups top assets by product route:
- **Poster candidate** — high `merch_score`, strong silhouette, graphic potential
- **T-shirt candidate** — high `identity_score`, wearable framing
- **Social-only candidate** — high `social_score`, high `emotional_score`, poor merch framing

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
