# Decision & Progress Tracking

## Current Status

**Phase:** Pre-code — architecture decided, seed data in Atlas, implementation not started  
**Deadline:** June 11, 2026 @ 2:00 PM PDT  
**Partner track:** MongoDB

---

## Decision Log

### D-000 — Partner Track: Elastic (superseded)
**Date:** 2026-05-23  
**Superseded by:** D-001  
**Original rationale:** Elastic framed as "retrieval-driven operational intelligence" — semantic search over media assets and historical campaign data  
**Why it didn't hold:** Gemini handles the actual reasoning. Elastic's role was one `search_assets` call with synthetic seeded data. MCP was decorative, not load-bearing.

---

### D-001 — Partner Track: MongoDB (supersedes D-000)
**Date:** 2026-05-23  
**Decision:** MongoDB, not Elastic

**Reasoning:**
- Applied the load-bearing test: *would removing this MCP cripple the agent?*
- MongoDB MCP is called in every one of the 8 workflow steps: ingestion, event context, vector search scoring, state updates, campaign queue, approval queue, execution logging, feedback loop
- Elastic's role reduced to ~1 retrieval query that Gemini could handle in-context. Not load-bearing.
- Elastic's partner page listed technical resources as "Coming soon" — real execution risk against a 19-day runway
- MongoDB has well-documented MCP server, sample datasets with pre-built vector embeddings, no access friction

**Fivetran ruled out simultaneously:**
- Fivetran is a data warehouse ingestion tool (source → BigQuery/Snowflake), not a vendor pipeline
- Printful/Printify expose REST APIs, not Fivetran connectors
- Fivetran's batch/scheduled architecture directly contradicts the "attention half-life" latency narrative

---

### D-002 — Core Intelligence Layer
**Date:** 2026-05-23  
**Decision:** Per-channel image similarity to past performers via vector search — not virality prediction  
**Rationale:** Virality prediction is pseudoscientific and unvalidatable in a hackathon demo. "Operationalizes historically correlated signals" is more credible and more defensible to judges. Vector search over past campaign performance grounds scoring in actual data.

*Framing later sharpened in D-014.*

---

### D-003 — MVP Scope Constraints
**Date:** 2026-05-23  
**Decision:** Hard limits enforced  
- One event type: World Cup soccer  
- Social: simulated (superseded "TBD: Instagram" — see D-007)  
- One ecommerce system: Shopify  
- Product types: poster, t-shirt (2 max)  
- Human approval required before any execution  
**Rationale:** Scope creep kills hackathon projects. Narrow enough to finish; wide enough to demonstrate full workflow.

---

### D-004 — Project Positioning
**Date:** 2026-05-23  
**Decision:** "Real-time event commerce operations agent" — not "AI for creators," not "AI photo sorter," not "AI marketing platform"  
**Rationale:** Operational framing sounds enterprise-capable and differentiates from commodity content tools. Judges need to see a workflow system, not a content optimizer.

*Framing later sharpened in D-014.*

---

### D-005 — Agent Runtime: Google ADK v2.1 + Cloud Run (updated by D-011)
**Date:** 2026-05-23 (updated 2026-05-23)  
**Decision:** Google ADK v2.1 for agent orchestration and state machine; hosted on Cloud Run  
**Ruled out:** Google Cloud Agent Builder (limited MCP client control); LangChain + LangGraph (initially chosen, superseded after spike confirmed ADK viability)

**Reasoning:**
- Spike (D-011) confirmed ADK v2.1 HITL suspend/resume works correctly — both pass criteria met
- ADK has native `McpToolset` built-in — no external adapter needed vs. `langchain-mcp-adapters`
- Google ADK on a Google Cloud hackathon is a genuine optics advantage — judges are GCP engineers
- LangChain remains a valid fallback if ADK hits unexpected issues in implementation
- Cloud Run is the natural hosting target for Python agent backends (listed in spec for custom backends)
- Model: `gemini-2.5-flash-lite` (confirmed working; `gemini-2.0-flash` deprecated for new users)

---

### D-006 — Vector Embedding Provider: Gemini `gemini-embedding-2`
**Date:** 2026-05-23  
**Decision:** Gemini `gemini-embedding-2` via Vertex AI  
**Ruled out:** Voyage AI `voyage-multimodal-3.5`

**Reasoning:**
- Voyage AI is a separate AI company — not a "built-in feature" of MongoDB, just a recommended pairing. Falls under "all other AI tools not permitted" in the hackathon rules. Real compliance exposure.
- `gemini-embedding-2` is 3072 dimensions (vs. Voyage's 1024 default) — higher semantic precision for image similarity
- Same GCP credential chain as the rest of the stack — no separate API key or billing account
- One less service dependency on a 19-day timeline

---

### D-007 — Social Platform: Simulated (no live API)
**Date:** 2026-05-23  
**Decision:** Simulate social post step — no live platform API  
**Ruled out:** Instagram (Meta app review required for posting to other accounts; setup friction fragile for demo); X/Twitter (API docs return 402 Payment Required — paywalled write access)

**Reasoning:**
- The demo value is in orchestration, not whether pixels appear on a live feed
- Agent creates a complete post package: image, caption, hashtags, optimal timing → writes to MongoDB with `status: "queued"` after human approval
- Eliminates the riskiest external dependency from the demo path

---

### D-008 — Ecommerce: Shopify Partners Dev Store + GraphQL Admin API
**Date:** 2026-05-23  
**Decision:** Shopify Partners dev store (free), GraphQL Admin API  
**Ruled out:** Real paid store (unnecessary cost and overhead for a demo)

**Reasoning:**
- Shopify Partners account is free, provides unlimited development stores
- Dev stores support full Admin API access
- REST API for products deprecated as of 2024-04 — use GraphQL Admin API
- Requires `products` access scope; draft orders also supported

---

### D-009 — Print-on-Demand: Printful
**Date:** 2026-05-23  
**Decision:** Printful  
**Ruled out:** Printify (OAuth app registration takes ~1 week; no sandbox)

**Reasoning:**
- Printful: free account, mockup generator API documented, REST-based
- Mockup API is async: `POST /mockups` to create task → `GET /mockups/{task_id}` to poll — fits cleanly into an ADK retry loop via `LongRunningFunctionTool`
- Printify personal token is fast but OAuth registration (needed for proper app integration) takes ~1 week — too slow for this timeline

---

### D-010 — Demo Assets: Wikimedia Commons
**Date:** 2026-05-23  
**Decision:** Source 20–50 freely licensed soccer/sports photos from Wikimedia Commons  
**Ruled out:** Unsplash (license requires attribution, restricts competing with Unsplash); Gemini image generation (adds infrastructure complexity, generated images look artificial)

**Reasoning:**
- Wikimedia Commons has large collections of freely licensed sports/soccer photos (CC BY-SA, CC BY) — verifiable licenses, zero API needed
- Download a fixed seed batch for the demo — deterministic, reproducible, no rate limits
- Real photos give the demo more credibility than AI-generated images

---

### D-011 — ADK v2.1 Spike: PASS — switch to ADK
**Date:** 2026-05-23  
**Decision:** Google ADK v2.1 confirmed viable; supersedes LangGraph (D-005 updated)

**Spike results** (`spike/adk_hitl_test.py`):
- HITL suspended correctly: **PASS** — `LongRunningFunctionTool` emitted `long_running_tool_ids`, runner suspended
- HITL resumed correctly: **PASS** — `FunctionResponse` resume worked, agent produced coherent final response
- Model: `gemini-2.5-flash-lite` (required — `gemini-2.0-flash` deprecated for new API users)

**Notes:**
- `McpToolset` is built into ADK — cleaner than `langchain-mcp-adapters`
- OTel context warning on generator exit is cosmetic noise, not a functional issue
- LangGraph remains a documented fallback if implementation hits ADK-specific blockers

---

### D-012 — MongoDB Schema Field Naming: Schema.org Alignment
**Date:** 2026-05-23  
**Decision:** Align `events` and `assets` collection field names with Schema.org where a standard equivalent exists; define freely elsewhere.

**Field renames applied:**

| Collection | Old field | New field | Schema.org source |
|---|---|---|---|
| `events` | `match` | `name` | `Event.name` |
| `events` | `teams[]` | `home_team`, `away_team` | `SportsEvent.homeTeam/awayTeam` |
| `events` | `venue` | `location` | `Event.location` |
| `events` | `kickoff_utc` | `start_date` | `Event.startDate` |
| `events` | `result` | `final_score` | (custom — no Schema.org equivalent; rename for clarity) |
| `assets` | `file_path` | `content_url` | `ImageObject.contentUrl` |
| `assets` | `ingested_at` | `upload_date` | `ImageObject.uploadDate` |

**Ruled out:** Schema.org adoption for `campaigns`, `approvals`, `performance` — no useful standard exists for those models.

---

### D-013 — Scoring Dimension Redesign
**Date:** 2026-05-23  
**Decision:** Restructure the 5 asset scoring dimensions; move timeliness to event level.

| Original | New | Change |
|---|---|---|
| `quality_score` | `quality_score` | **Added** — technical fitness gate (sharpness, exposure, printability) |
| `emotional_score` | `emotional_score` | Kept; rubric sharpened: intrinsic moment intensity in the frame |
| `social_score` | `social_score` | Kept; rubric sharpened: scroll-stopping visual properties at thumbnail scale |
| `merch_score` | `merch_score` | Kept; subject suitability for physical product |
| `identity_score` | `identity_score` | Kept; team/player recognition clarity |
| `timeliness_score` (asset) | `timeliness` (event) | **Moved** to `events` document; computed deterministically, not via Gemini Vision |

**Rationale:**
- `timeliness_score` on assets was category confusion — it's an event property, not an image property; every image from an `upset_victory` gets the same value
- `quality_score` added because merch routing requires technical fitness — a blurry iconic image is unprintable regardless of subject matter
- `emotional_score` and `social_score` kept separate: emotional = moment intensity; social = thumb-stopping visual properties at thumbnail scale — these diverge meaningfully for soccer photography

*Dimension types and per-queue roles further refined in D-017.*

---

### D-014 — Project Reframe: Similarity-Based Logistics, Not Intent Detection
**Date:** 2026-05-24  
**Decision:** The system is a **commercial logistics coordinator** whose engine is per-channel image similarity to past performers — not a commercial intent detector or virality predictor.  
**Supersedes framing in:** D-002, D-004

**What changed:**
- Removed all "intent detection" language from specs and positioning
- The honest claim: find assets that look like past channel winners → get them to market before the attention window closes
- Scoring dimensions assess *historically correlated signal*, not commercial intent
- "Predicts virality" → "image similarity to past performers, deployed before the attention window closes"

**Why this matters for the demo:**
- "Intent detection" is unvalidatable and invites judge skepticism
- Logistics + speed framing is more defensible: the value is operational velocity, not AI cleverness
- Removing MongoDB still breaks the system (vector search over past performers); the MCP is genuinely load-bearing under this framing

---

### D-015 — Exploration vs. Exploitation: Two-Queue Architecture
**Date:** 2026-05-24  
**Decision:** 90% exploitation queue (top-K by similarity) + 10% random discovery queue (sampled from low-similarity remainder). Random is the MVP default.

**Problem addressed:** Pure similarity ranking systematically excludes novel content before the human sees it. The HITL gate is downstream of the filter and cannot correct for this exclusion.

**Resolution:**
- All images are similarity-scored in Step 3
- Top-K by similarity score → **exploitation queue**
- Random 10% sample from low-scoring remainder → **discovery queue**

**Why random, not tail-sampling or diversity constraints:**
- Any non-random filter reintroduces an exclusion criterion at a smaller scale
- Random makes no claim about what novelty looks like — maximally honest
- Some discovery slots will surface mediocre images; that is the honest cost of genuine exploration

**Tuning space deferred as customer decision:** random / low-similarity tail / diversity constraints / novelty-scored queue. Different operators want different discovery behavior. Not a fixed design.

---

### D-016 — Step 2 Structured Event Narrative + `player_context` RAG
**Date:** 2026-05-24  
**Decision:** Step 2 produces a typed **event narrative** (not prose) consumed by Step 5 as copy substrate. Player biographical facts are retrieved from a `player_context` collection — not inferred by the LLM.

**Problem addressed:** Original Step 2 produced "reasoning output" with no named downstream consumer. Without a consumer, it was LLM theater. Step 5 generated generic copy that could have come from any event.

**Resolution:**
- Step 2 LLM output: narrative angle, key figures with grounded facts, commercial timing, historical baseline
- Step 5 consumes this as copy substrate → headlines become specific and factually grounded
- `player_context` is a static reference corpus: player biographical facts + `commercial_signal` editorial pre-rating
- Lookup: plain team-name match against `events.home_team` / `events.away_team` — no vector search
- Retrieved once per event batch in Step 2, not once per asset in Step 5

**What this enables:** *"Messi ends France's reign in extra-time thriller — limited edition print"* vs. *"Argentina beats France — World Cup 2026 poster"*

---

### D-017 — Step 4 Dual-Job: Technical Fitness vs. Commercial Signal, Per-Queue
**Date:** 2026-05-24  
**Decision:** Step 4's five dimensions split into two distinct types with different roles per queue.

**Two dimension types:**

| Type | Dimensions | Character |
|---|---|---|
| Technical fitness | `quality_score`, `merch_score` | Near-objective observable properties |
| Commercial signal | `emotional_score`, `social_score`, `identity_score` | Interpretive assessment of observable qualities that correlate with commercial outcomes |

**Per-queue role:**

*Exploitation queue:* channel routing is already implied by similarity results (past assets carry `product_route`). Step 4 adds a **quality gate** — technical fitness dimensions catch images that are compositionally similar to past winners but technically unfit for production (motion blur, low resolution, cluttered background). All five dimensions then provide ranking refinement within a channel.

*Discovery queue:* no per-channel similarity signal is available. Step 4 is the **sole routing suggestion** — technical fitness confirms the frame is viable; commercial signal indicates whether the image has qualities worth surfacing despite low similarity. The contrast signal (low similarity + high dimensional score) is the human-facing value: *"This image didn't match past winners, but it's sharp and emotionally intense — poster potential, your call."*

**Language discipline:** "commercial signal" or "commercially correlated qualities" — never "commercial intent" (overclaim) and never "physical properties only" (overcorrection).

---

## Planning Document Index

| File | Role | Status |
|------|------|--------|
| `rapid_agent_hackathon_spec.md` | Hackathon rules, partner details, judging criteria | Reference — do not modify |
| `CLAUDE.md` | Index — see docs/specs/ for spec files | Current |
| `docs/specs/00-overview.md` | Vision, origin, positioning, demo narrative | Current |
| `docs/specs/01-requirements.md` | Functional spec, 8-step workflow, MVP scope | Current |
| `docs/specs/02-architecture.md` | System design, schemas, MCP call list | Current |
| `tracking.md` | This file — decision log | Current |

Deprecated planning docs moved to `deprecated/` (gitignored).
