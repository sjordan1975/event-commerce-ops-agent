# Decision & Progress Tracking

## Current Status

**Phase:** Strategic-agent reframe complete (D-021); propagation in progress. Step 0/0.5 foundation merged; Step 1 docs being rewritten against the new capability surface before implementation begins.  
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

### D-015 — Exploration vs. Exploitation: Two-Queue Architecture (exploration default updated by D-021)
**Date:** 2026-05-24 (updated 2026-05-26)  
**Decision:** 90% exploitation queue (top-K by similarity) + 10% random discovery queue (sampled from low-similarity remainder). Random was the MVP default until D-021; the two-queue structure persists, and random remains the documented fallback configuration. The MVP demo now uses agent-driven novelty selection for the discovery queue per D-021.

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

### D-018 — Tool Surface: Raw McpToolset for MongoDB, FunctionTool for Non-MongoDB (superseded)
**Date:** 2026-05-24  
**Superseded by:** D-019  
**Decision:** Agent calls raw MongoDB MCP tools directly (find, insert-many, update-many, aggregate, vectorSearch). Python `FunctionTool` is reserved for non-MongoDB capabilities only.

**Spike results** (`spike/adk_mcp_raw_test.py`):
- Find with filter (outcome_type = upset_victory on event_commerce.events): **PASS** — agent called correct tool with correct database, collection, and filter shape
- Insert document (7-field event document): **PASS** — agent called `insert-many` with all fields correct; insertion confirmed in Atlas
- Cleanup delete: **PASS** — document removed
- Model: `gemini-2.5-flash-lite` (same as D-011 spike)

**What belongs in FunctionTool:**
- `compute_timeliness(outcome_type, kickoff_ts) -> float` — pure math, no DB
- Shopify GraphQL calls (not MCP)
- Printful REST calls (not MCP)
- `LongRunningFunctionTool` at Step 6 HITL gate (ADK requirement)

**What belongs in raw MCP:**
- All MongoDB reads and writes across all 8 steps
- Vector search (`vectorSearch`) in Step 3
- Aggregation (`aggregate`) in Steps 2, 4, 8

**Why this matters for the demo:**  
MongoDB operations appear in the agent's reasoning trace — judges can see the agent planning which collection to query, which filter to apply, what data to insert. Hiding MongoDB inside Python wrappers would make it invisible. Raw MCP is what "load-bearing, not cosmetic" means.

**Rejected alternative:** `ingest_event` FunctionTool that wraps `events.insertOne` + `assets.insertMany` in one call. This hides MongoDB from the trace and contradicts the hackathon's "partner superpowers" framing.

---

### D-019 — Tool Surface: Domain Wrappers over MongoDB MCP (supersedes D-018)
**Date:** 2026-05-25  
**Decision:** The agent's tool surface is a set of domain-named Python `FunctionTool` wrappers (e.g. `get_player_context`, `find_similar_assets`, `record_ingested_event`). Each wrapper calls MongoDB MCP internally via the McpToolset client. Raw MCP tools are not exposed to the agent.

**What changed from D-018:**
- D-018 reasoned that exposing raw MCP to the agent would showcase MongoDB as load-bearing in the trace. That argument conflated two things: (A) MongoDB doing genuinely important work in the system, and (B) the agent reasoning in raw MongoDB terms. (A) is what "load-bearing" means; (B) is performative. The tool-call shape carries no information about which database is behind it — `get_player_context(team)` and `find({"team": team})` are indistinguishable as evidence of "MongoDB integration." MongoDB is showcased by the architecture, vector index, schema design, and demo narrative — not by the agent constructing raw filters.
- The D-018 spike (`spike/adk_mcp_raw_test.py`) is not invalidated. It demonstrated that the model *can* construct correct MCP calls when given the schema. D-019 chooses not to put that capability on the agent's runtime path because the engineering trade-offs (token cost, schema-drift fragility, hallucination surface, debuggability) favor wrappers even though raw works.

**Three project phases this clarifies:**
1. **Discovery** (out-of-band, engineering time) — read MongoDB MCP server docs; understand the tools it exposes (find, insert-many, update-many, aggregate, vectorSearch, etc.); decide which we'll use internally. *The naive trap is treating this as a runtime concern where the agent "figures it out."*
2. **Build** (engineering time) — implement domain wrappers in `src/db/` that map to project semantics (`get_player_context`, `find_similar_assets`, `record_ingested_event`, etc.). Wrappers handle field names, normalization, Pydantic validation, and call MongoDB MCP through the McpToolset client.
3. **Runtime** (demo day) — agent calls only domain wrappers. McpToolset is still wired (Step 0) but is infrastructure under the wrappers, not a tool surface for the agent.

**System prompt still carries schema — at the conceptual level, not the field-construction level:**

The agent benefits from knowing the data model (what kinds of records exist, how they relate) so it can reason about which wrapper to call. It does *not* need field-level detail for filter construction — that's the wrapper's job. Example style for the prompt:

```text
Schema overview:
- Event records are stored in the `events` collection; each event has a unique event_id.
- Image records are stored in the `assets` collection; each asset references one event via event_id.
- Player biographical facts are stored in the `player_context` collection, keyed by team name.
- Past performance data drives vector search via the `find_similar_assets` tool.
```

**What belongs in domain wrappers:**
- All MongoDB reads, writes, updates, aggregates, and vector searches across all 8 steps
- Document construction guarded by Pydantic models
- Field-name discipline contained in one layer

**What stays as direct FunctionTools (non-MongoDB):**
- `compute_timeliness(outcome_type, kickoff_ts) -> float` — pure math
- Shopify GraphQL calls
- Printful REST calls
- `LongRunningFunctionTool` at Step 6 HITL gate (ADK requirement)
- Gemini embedding generation (Vertex AI, not MongoDB)

**Naming discipline so MongoDB's distinctive work stays legible:**
Wrappers around the load-bearing MongoDB features should be named such that a reader of the code or architecture doc can see what MongoDB feature is behind them. `find_similar_assets` (clearly vector search), not `get_recommendations` (database-agnostic). Wrapping is fine; obscuring is not.

**Trade-offs accepted:**
- Less of the agent's MongoDB knowledge visible in the trace. Replaced by architecture diagram + index definitions + named wrappers in the codebase. Net: demo narrative is at least as strong, more robust.
- Up-front engineering cost to build the wrapper layer before Step 1. Recovered by shorter prompts, fewer hallucination paths, simpler tests.

**Full wrapper inventory:** see `docs/plans/db-wrapper-inventory.md`.

---

### D-020 — Evaluation is a First-Class Engineering Concern
**Date:** 2026-05-25  
**Decision:** Trace-based evals (per-step + integration + repetition for failure rate) are required for every workflow step. They are not optional, not "if we have time," and not replaced by manual smoke tests.

**Why this decision exists:**
Agentic systems fail statistically, not deterministically. A smoke test that passes once is not evidence the system works — a single passing run on `gemini-2.5-flash-lite` says nothing about pass rate across 20 runs, or behavior under a prompt change, or robustness when the tool surface grows. The cost of treating evals as optional is a demo that fails on stage from a failure mode that was always present but never measured.

**What this commits us to:**
- Every step's `Verify` checkpoints include at least one trace-based eval (under `tests/evals/`)
- Failures dump full traces (tool calls + args + outputs + LLM reasoning text) for diagnosis
- Pass rate ≥ 95% across 20 repetitions is the ship gate per step; rates below trigger remediation (prompt tightening → docstring tightening → surface change → hybrid wrapper defense → model swap)
- The five failure categories (tool selection, sequencing, argument, output handling, end-state) each have a detection mechanism

**Specific connection to D-019 Q#6 (timeliness chain):**
The agent calls `compute_timeliness` explicitly and chains the result into `record_event` because that chain demonstrates the agentic premise. The risk of that decision (the agent could hallucinate the value or skip the call) is mitigated by the trace eval, not by hiding the computation in the wrapper. If the eval shows < 90% pass rate, the hybrid fallback wrapper kicks in. This is the pattern for every decision where we trade agentic legibility against statistical reliability — evals are the instrument that tells us which side wins.

**Full framework:** see `docs/plans/evaluation-strategy.md`.

**What we are explicitly not doing for MVP:** LLM-as-judge for quality, cross-model behavioral diffs, statistical significance testing, adversarial probes, cost budgets. Listed in the strategy doc so we don't accidentally pretend to have them.

---

### D-021 — Strategic-Agent Reframe: Procedural → Strategist with Queue Assembly
**Date:** 2026-05-26  
**Decision:** The agent is reframed from procedural enacter of an 8-step workflow to **strategist that assembles the operator review queue** for a given event, then executes against the approved queue. The 8 steps become 9 mid-granularity capabilities the agent composes; **queue assembly is the single strategic decision**.

**Updates:** D-015 — exploration queue's selection mechanism changes from random sampling to agent-driven novelty selection for the MVP demo; random retained as the documented fallback config. The two-queue structure itself is unchanged.

**What changed and why:**

The pre-reframe design treated the 8-step workflow as the agent's job — the agent re-derived, every run, what we already wrote down in tool docstrings (*"call X before Y"*). That is not where agentic value lives. Most of the strategic surface was already mechanized by D-015 (two-queue split), D-016 (Step 2 narrative + `player_context` RAG), and the similarity-grounded routing of Step 3 — the agent's role collapsed to enacting a known path. We were forcing an agentic shape onto a workflow-shaped problem.

The reframe exposes the one place where the existing spec admits it has no deterministic answer: the exploration queue. The agent's strategic job becomes **assembling the operator review queue** — exploration selection (which non-similar assets to surface, with per-image reasoning), exploitation ordering (the agent's fingerprints on similarity results), and per-item reasoning throughout. This is type-2 agentic value (judgment under bounded ambiguity), not type-1 (large-surface exploration).

**Headline consequences:**

- **Capability surface:** 9 mid-granularity capabilities the agent composes — `ingest_event_batch`, `build_event_context`, `find_similar_assets`, `score_assets_with_vision`, `propose_review_queue`, `draft_campaigns_for_queue`, `request_human_approval`, `execute_approved_campaigns`, `record_outcomes`. `find_similar_assets` and `score_assets_with_vision` are explicit (not bundled into queue assembly) — preserves MongoDB demo legibility and separates computation from judgment.
- **Strategic decision:** `propose_review_queue` is the one strategic call. All other capabilities are computational, LLM-at-the-node, HITL, or external-API in kind.
- **Preconditions:** enforce data dependencies as hard-refuse with informative errors (`PreconditionError` with self-correcting message format); leave order among independent operations to the agent. The middle three capabilities (context, similarity, scoring) have no order constraint among themselves.
- **Demo shape:** two contrasting events (upset victory + group-stage draw); Event 1 full flow + Event 2 strategic-differences only; ~3-minute pacing; reproducibility via 95% pass-rate + multiple takes + curated asset corpus.
- **Step 1 reconciliation:** no implementation code exists yet, so reconciliation is doc rewrite only. `compute_timeliness`, `record_event`, `record_assets` survive as internal Python wrappers but are no longer agent-facing `FunctionTool`s. `ingest_event_batch` becomes the single Step 1 capability. Trace eval shifts from sequencing-shaped to outcome-shaped.
- **D-015 update:** structure unchanged (two-queue split persists). Default for exploration changes from random sampling to agent-driven novelty selection for the demo. Random retained as documented fallback configuration. D-015's own framing (*"expected to be tuned by customer and implementation"*) anticipated this — the change is a configuration choice, not a structural reversal.
- **Hard Constraint #1 in `CLAUDE.md` revises:** *"Do not simplify or merge the 8-step workflow"* → *"Do not remove capabilities or collapse the queue-assembly decision into a heuristic."*

**Full design rationale, capability table, precondition table, demo pacing, Step 1 reconciliation plan, and three-phase propagation plan:** see `docs/plans/strategic-agent-reframe.md`. Companion docs: `docs/plans/agentic-model.md` (agent loop shape) and `docs/plans/safety-measures.md` (loop and spend bounds).

**What this is not:**
- Not a pivot of the problem domain. Real-time event commerce, sports merchandise monetization windows, MongoDB-grounded similarity all unchanged.
- Not a framework change. ADK + MongoDB MCP + Gemini stack unchanged.
- Not a tear-up of existing code. Step 0/0.5 foundation reusable; Step 1 docs rewrite without code revert.
- Not an expansion of MVP scope. One strategic decision is *less* surface than the original 8-step framing implied. The agent's surface narrows even as its substance deepens.
- Not "every step is strategic." Most capabilities remain LLM-at-the-node-level. Agentic-strategic-ness lives in queue assembly. That is enough.

---

### D-022 — Persist Event Narrative on the `events` Document (refines D-016)
**Date:** 2026-05-27  
**Decision:** `build_event_context` writes the structured `EventNarrative` onto the producing `events` document as a new `event_narrative` field, in addition to returning the narrative to agent state for the current turn.

**Refines:** D-016. D-016's substance is unchanged — narrative is still a typed structured artifact, player facts are still retrieved from `player_context` by team-name match, and `draft_campaigns_for_queue` still consumes it as copy substrate. The framing that changes is the in-state-only paragraph carried forward into `docs/specs/02-architecture.md` § `build_event_context` (*"returned to agent state, consumed by `draft_campaigns_for_queue`"*) — now superseded by "persisted on the events doc and read by downstream capabilities from there."

**Why this matters:**
- `propose_review_queue` (capability 5 per D-021) has four hard preconditions, of which `event_narrative` is one. With persistence, the precondition check is a cheap `event.event_narrative is None` on a document the wrapper already has to read. Without persistence, the agent would have to pass the multi-hundred-token narrative payload as a tool-call argument every time queue assembly runs — inflating token cost, increasing the surface for the agent to lose/garble the artifact across turns, and forcing the same payload through any other downstream tool call that also needs it.
- Persistence also makes the narrative survive session reset: a resumed agent run reads the narrative from `events`, rather than having to recompute or be re-handed it.
- Cost is one additional `events.update-many` per `build_event_context` invocation — sub-100ms in practice and dominated by the network round-trip the capability already pays for its reads.

**Schema impact:**
- `events` documents gain optional `event_narrative` field (nullable; absent for events that have been ingested but not yet had context built).
- `Event` Pydantic model in `src/models.py` gains `event_narrative: EventNarrative | None = None`. Pydantic validates the nested shape at insert/update boundaries — a malformed narrative fails at write time, which is the bug-surface we want.
- `EventNarrative` and its nested types (`KeyFigure`, `HistoricalBaseline`) live in the same `src/models.py` file — no import cycle.

**MCP call list impact:** `build_event_context` adds one `events.update-many` call (filter by `event_id`, `$set: {event_narrative: ...}`). MongoDB MCP exposes `update-many` but not `update-one`; the filter is unique by `event_id`, so the semantics collapse to a single-document update.

**Out of scope:**
- D-022 does not change the narrative's typed structure, the LLM call shape (direct `google.genai` with `response_schema=EventNarrative`), the player_context retrieval strategy, or the downstream consumer in Step 5/6. It only changes *where the narrative lives between producer and consumers.*
- D-022 does not change agent-facing surface — `build_event_context` still returns the narrative dict from the FunctionTool call. Persistence is additive to the return.

**Full design context:** `docs/plans/step-2-context.md` § "Persistence: `event_narrative` field on `events`".

---

### D-023 — Recognized Architectural Debt: LLM-Driven vs Graph-Driven Orchestration
**Date:** 2026-05-27  
**Decision:** Accept LLM-driven tool selection for MVP; flag graph-based orchestration as the correct post-hackathon direction.

**Context:** Evals on Step 1 and Step 2 surfaced a reliability failure mode: after ingesting a batch, the agent sometimes chains to `build_event_context` even when the operator explicitly says "stop after ingestion." Root cause is that a single `LlmAgent` with all tools registered treats tool selection as a judgment call every turn — including decisions that are structurally determined.

**The transferable concept (LangGraph's `add_node`/`add_edge`):** In LangGraph, you wire execution order explicitly in the graph structure. The ADK equivalent is `SequentialAgent` for ordered pipelines and a coordinator `LlmAgent` for branch points. This approach makes deterministic steps deterministic — the graph enforces them, not the prompt.

**Why most of this workflow would benefit from graph structure:** Ingest → build context → find similar assets → score assets is a data-dependency pipeline, not a judgment call. Only `propose_review_queue` genuinely requires LLM judgment (exploitation/exploration selection and per-item reasoning). The rest is operational sequencing.

**Why we're not doing it now:** Switching `LlmAgent` to a `SequentialAgent` + strategic coordinator touches agent architecture, eval setup, and the HITL suspension pattern (which requires specific ADK handling for `LongRunningFunctionTool`). Scope risk against a tight deadline outweighs the reliability gain for a demo context.

**Mitigation for MVP:** System prompt now makes workflow steps explicitly numbered and adds "the operator drives the workflow — only proceed when instructed." Combined with PreconditionError enforcement, this reduces (but does not eliminate) unwanted chaining. Prompt-based control with N=5 pass-rate gates is the acceptance criterion.

**Post-hackathon direction:** Refactor to a coordinator `LlmAgent` that routes to specialized sub-agents or a `SequentialAgent` pipeline for the deterministic steps, with `LlmAgent` reserved for `propose_review_queue`. This eliminates the entire class of "agent chains to next step when it shouldn't" failures.

---

## Planning Document Index

### Specs and meta

| File | Role | Status |
| --- | --- | --- |
| `rapid_agent_hackathon_spec.md` | Hackathon rules, partner details, judging criteria | Reference — do not modify |
| `CLAUDE.md` | Project index; orientation; build practices | Current |
| `tracking.md` | This file — decision log | Current |
| `docs/specs/00-overview.md` | Vision, origin, positioning, demo narrative | Current |
| `docs/specs/01-requirements.md` | Functional spec, MVP scope, workflow | **Pending revision per D-021** (Phase A) |
| `docs/specs/02-architecture.md` | System design, schemas, MCP call list, ADK architecture | **Pending revision per D-021** (Phase A) |

### Cross-cutting design docs (`docs/plans/`)

| File | Role | Status |
| --- | --- | --- |
| `strategic-agent-reframe.md` | D-021 design doc — strategic-agent pivot, queue assembly, capability surface, preconditions, demo coherence, propagation plan | Current |
| `agentic-model.md` | What kind of agent this is — loop shape, exit conditions, HITL framing | **Pending revision per D-021** (pre-pivot framing) |
| `safety-measures.md` | Loop bound + spend bound — operational safety follow-ups | Current |
| `testing-model.md` | Three-category test model (unit / scaffolding / eval) | Current |
| `evaluation-strategy.md` | Trace-eval framework, failure categories, remediation playbook | **Pending revision per D-021** (gains *strategy coherence* failure category) |
| `db-wrapper-inventory.md` | Domain wrapper inventory under D-019 — internal MongoDB MCP plumbing | Current (wrappers themselves unchanged; agent-facing surface grouping changes per D-021) |

### Per-step plans and tasks

| File | Role | Status |
| --- | --- | --- |
| `docs/plans/step-0-foundation.md` | Step 0 — agent shell, MCP wiring, smoke tests | Complete — merged to `main` |
| `docs/tasks/step-0-tasks.md` | Step 0 task list | Complete |
| `docs/plans/step-0.5-refactor.md` | Step 0.5 — D-019 enforcement (no raw MCP in `agent.tools`) | Complete — merged to `main` |
| `docs/plans/step-1-event-ingestion.md` | Step 1 — event + asset ingestion | Complete — merged to `main` |
| `docs/tasks/step-1-tasks.md` | Step 1 task list | Complete — merged to `main` |

Deprecated planning docs moved to `deprecated/` (gitignored).
