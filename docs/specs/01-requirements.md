# 01 — Requirements: Functional Specification

> **Updated for D-021** (2026-05-26) — the agent's job is reframed as **strategic queue assembly** composed of 9 capabilities. The pre-pivot "8-step workflow" framing is superseded. Sections updated: routing strategy, agent capabilities (was: 8-step workflow), demo flow, judging alignment, success metrics. Sections unchanged: hackathon non-negotiables, MVP scope, asset routing, channel responsibility, performance metrics, non-goals. Full design rationale: `docs/strategic-agent-reframe.md`; D-021 in `tracking.md`.

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

**Time window:** rolling 7 days from publish time (recorded as `window_start`, anchored on the campaign's `execution.executed_at`). All metrics represent cumulative totals within that window. The `window_days` field is stored on each document for traceability.

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

### Routing strategy: similarity-driven exploitation + agent-driven exploration

The MVP uses similarity-based prioritization for the main exploitation queue, with a 10% exploration budget surfaced by **agent-driven novelty selection** (per D-021, superseding D-015's random-sampling default for the MVP demo).

**Exploitation queue (90%):** top-K assets by per-channel similarity score — the exploitation path. Assets that resemble past performers. Routing implied by similarity. The agent orders the queue based on event-narrative fit (per-item reasoning attached to each surfaced item).

**Exploration queue (10%):** assets that did *not* match past winners by similarity, selected by the agent for surfacing to the operator. Each selection carries the agent's one-sentence rationale for why it is worth the operator's time despite the similarity miss. This is the one place in the system where the agent reasons without a deterministic crutch — no similarity signal, no past-performer template, just an image and a judgment call.

The human operator reviews both queues and decides. The algorithm surfaces exploitation candidates; **the agent surfaces exploration candidates with reasoning**; editorial judgment advances them.

**Why agent-driven exploration for the demo:** the exploration queue is the canonical judgment-under-bounded-ambiguity case. Random selection (D-015's default) is honest but produces no visible reasoning. Agent-driven selection surfaces the agent's judgment — *"this is worth your time despite the miss because X"* — which is the load-bearing demonstration of strategic AI value (per `docs/strategic-agent-reframe.md`).

**Tuning space (customer/implementation decision):**

The right exploration strategy is a configuration decision, not a fixed design. The MVP demo uses agent-driven novelty; alternatives remain valid configurations:

- **Agent-driven novelty (MVP demo default — D-021):** the LLM picks exploration candidates with per-image reasoning. Visible judgment; structurally biased by whatever criteria the agent uses.
- **Random sampling (D-015 documented fallback):** maximally honest — any candidate can surface regardless of how divergent. No visible reasoning.
- **Low-similarity tail:** biased toward visually distinct outliers; for customers who specifically want to see the most divergent images.
- **Diversity constraints:** force the top-K to include assets dissimilar from each other — broader coverage without full random selection.
- **Novelty-scored queue:** score candidates explicitly for divergence from the existing corpus; algorithmically curated surprise.

**Framing for judges:** *"Exploration is where the agent earns its keep. Without a similarity signal to lean on, the agent has to reason: which images are worth the operator's time despite not matching past winners? That reasoning is on screen, per-item, throughout the demo. The right exploration strategy is a customer decision — we ship agent-driven novelty as the demo default; random remains a valid fallback."*

### Routing mechanics (precise)

**Exploitation path — mechanically locked, LLM cannot override:**
`find_similar_assets` embeds each incoming image and runs Atlas vector search against the historical seed corpus. The top-k neighbors each carry a curated `product_route`. `_infer_route_from_neighbors` computes a similarity-weighted plurality vote over those routes — the winner becomes `inferred_route`. `persist_review_queue` writes that value directly to the asset; the LLM's output is ignored for this field. The seed corpus is the only thing that matters here: if seed routes are wrong, exploitation routes are wrong.

**Discovery path — LLM judgment, seed corpus irrelevant:**
Images that fall below the similarity cutoff have no neighbor signal. The LLM (`propose_review_queue` node) receives each discovery candidate's Step 4 vision scores (`quality`, `merch`, `identity`, `social`, `emotional`) plus `detected_subjects` (identifiable players/people from the vision model) and the event narrative. It decides whether to surface the asset at all, and if so, assigns a `product_route` (poster / tshirt / social_only). The seed corpus has zero bearing on this decision — only the live vision scores of the images currently being processed matter.

**Calibration gap (known limitation):**
The exploitation path is grounded — routing is only as good as the seed corpus, which is now human-curated. The discovery path is uncalibrated LLM judgment. A rigorous eval would require a human-scored reference set (images scored on all 5 dimensions with human-assigned routes) to measure how well the LLM's routing decisions match human judgment. Without this, discovery routing is a reasonable heuristic but not a validated signal. This is an enterprise-path concern; the demo demonstrates the mechanism, not calibrated accuracy.

---

## Non-Goals

- Not a chatbot or conversational assistant
- Not a general-purpose content generator
- Not an aesthetic image ranking tool
- Not a social media captioning tool in isolation
- Not a virality prediction system

---

## Operator Interaction Model

The operator submits a batch via a natural language chat message — describing the event outcome in sports vocabulary, providing photo file paths, and giving any relevant context. The agent extracts structured `event_metadata` (teams, score, start time, outcome type) from that message before calling `ingest_event_batch`.

**Sample batch submission:**

```text
Argentina pulled off the upset, beating France 3-2.
Photos at /tmp/wc-final/. Match started 19:00 UTC. Ingest this batch.
```

This design assumes a **sports-fluent operator**: someone who naturally uses domain vocabulary ("upset", "extra time", "draw") rather than selecting from a structured form. The agent's `outcome_type` extraction relies on that vocabulary — it is a one-hop classification from the operator's own framing, not an inference from team rankings or historical data. If the operator's message lacks a classification cue, the agent should ask before proceeding.

**Bidirectional agency:** the agent does not merely respond to operator prompts — it initiates clarification when inputs are ambiguous. Both directions (operator-to-agent submission and agent-to-operator clarification) require operator presence.

**Operator presence assumption:** the MVP assumes the operator is present for the full batch lifecycle — submission, optional clarification, and approval. The agent does not time out HITL waits; it holds until the operator responds.

**Home/away convention:** in "X vs Y" fixture notation, X is the home team (following FIFA fixture listing convention). This applies even at neutral-site tournaments — FIFA formally assigns home/away status to every fixture regardless of geography.

**Enterprise path:** structured batch submission form with dropdown `outcome_type` selection; natural language description becomes optional annotation rather than the classification source; and unattended batched processing (no clarification path).

---

## Agent Capabilities and the Strategic Decision

The agent composes **nine mid-granularity capabilities** to take a batch of event photos through to approved, published campaigns. Eight of them are mechanical, LLM-at-the-node, HITL, or external-API in kind — they do what they say with bounded reasoning. The ninth, `propose_review_queue`, is the **one strategic decision** the agent makes per event: how to assemble the operator review queue.

Capability ordering is dependency-aware (you cannot draft for a non-existent queue), but the middle three computational capabilities (`build_event_context`, `find_similar_assets`, `score_assets_with_vision`) have no order constraint among themselves — the agent picks. Preconditions are enforced by wrapper-level validation (`PreconditionError`); the agent receives a self-correcting error if it calls a capability before its data dependencies are met. Order among independent operations stays emergent.

Full design rationale: `docs/strategic-agent-reframe.md`. Loop shape and exit conditions: `docs/agentic-model.md`.

### The strategic decision: queue assembly

Given a batch of photos for an event, `propose_review_queue` outputs *a ranked, reasoned queue tailored to this event*:

- **Exploration selection** — which assets that did *not* match past winners by similarity are still worth surfacing, and why. The canonical judgment-under-bounded-ambiguity surface. Replaces D-015's random-sampling default per D-021 (random retained as fallback config).
- **Exploitation ordering** — similarity gives a top-K set; the order in which they reach the operator is the agent's judgment, based on event-narrative fit, reviewer workflow, or other domain reasoning.
- **Per-item reasoning** — every queued item, exploitation or exploration, carries a one-sentence rationale the operator can read. Exploitation items get "narrative fit" reasoning; exploration items get "why this is worth your time despite the miss" reasoning. This is what makes the agent's strategy legible.

This is type-2 agentic value: judgment under bounded ambiguity in a small action space. The agent is not exploring the Internet; it is deciding *"given this event, what is the right operator review queue?"*

### The nine capabilities

| # | Capability | Kind | What it does |
| --- | --- | --- | --- |
| 1 | `ingest_event_batch` | computational | Records the event document (with computed `timeliness`) and bulk-inserts all images at `status: "ingested"`. |
| 2 | `build_event_context` | computational + LLM | Aggregates event, past-performance, and `player_context` data; produces a structured **event narrative** consumed by `draft_campaigns_for_queue`. |
| 3 | `find_similar_assets` | computational | Embeds candidate images and runs vector search against the `assets` collection — the **primary load-bearing MCP step**. |
| 4 | `score_assets_with_vision` | computational + LLM | Runs Gemini Vision on each asset, writing 5-dimensional scores (`quality`, `emotional`, `social`, `merch`, `identity`). |
| 5 | **`propose_review_queue`** | **strategic — the one decision** | Takes similarity results + scores + narrative; outputs ranked queue with exploration selection, exploitation ordering, and per-item reasoning. |
| 6 | `draft_campaigns_for_queue` | LLM | Generates copy per queue item using the event narrative as substrate; creates campaign documents and approval records. Handles the redraft case (takes operator edit notes when present). |
| 7 | `request_human_approval` | HITL — `LongRunningFunctionTool` | Suspends. Resumes with approved / rejected / edit_requested decisions per item. |
| 8 | `execute_approved_campaigns` | external APIs | Shopify GraphQL + Printful REST + social-queue write. Internal retry on Printful mockup polling. |
| 9 | `record_outcomes` | computational | Writes post-execution metrics to the `performance` collection — feeds similarity search in future runs. |

### What each capability accomplishes (the substance)

**1. `ingest_event_batch`** — Operator provides the image batch (paths or blob references) plus event metadata (match result, teams, venue, kick-off time, outcome type from `upset_victory | extra_time_win | expected_win | draw`). The capability computes the event-level `timeliness` (`base_score × 0.5^(hours_since_kickoff / 4)`), writes the event document, and bulk-inserts all images with `status: "ingested"`. Internal wrappers (`compute_timeliness`, `record_event`, `record_assets`) handle the sub-operations; the agent does not see them as separate tools.

**2. `build_event_context`** — Retrieves the event record, aggregates historical conversion performance for events of the same outcome type, and looks up squad members for both teams from the `player_context` collection. The LLM produces a structured **event narrative** — not prose, but a typed output:

- **Narrative angle:** the story the event tells ("upset victory," "extra-time drama," "defending champions eliminated")
- **Key figures:** players with grounded biographical facts retrieved from `player_context` — not inferred by the LLM
- **Commercial timing:** aggressiveness of the routing window given `timeliness` and outcome type
- **Historical baseline:** which product types performed best for this outcome type in past events

Player context is retrieved here — once per event batch — not per asset. Downstream consumer is `draft_campaigns_for_queue`; the narrative is what makes campaign headlines specific and factually grounded rather than generic or hallucinated.

**3. `find_similar_assets`** — Embeds each candidate image using `gemini-embedding-2` (3072 dimensions) and runs vector search against the `assets` collection to find visually/semantically similar past assets with known per-channel performance data. **Primary load-bearing MCP step.** The engine is per-channel image similarity to past performers. Results carry `product_route` from past assets, so channel routing is implied by majority-channel of nearest neighbors. Removing MongoDB removes this signal — routing degrades to pure LLM inference with no historical grounding.

The top-K by similarity score form the **exploitation queue** candidate set. The remainder — images whose similarity score fell below the exploitation cutoff — form the candidate pool that `propose_review_queue` reasons over for exploration selection.

**4. `score_assets_with_vision`** — Gemini Vision scores every image across five dimensions, split into two types per D-017:

*Technical fitness* (near-objective, observable properties):
- `quality_score` — sharpness, exposure, resolution, printability
- `merch_score` — silhouette clarity, graphic potential, poster framing

*Commercial signal* (interpretive assessment of observable qualities that correlate with commercial outcomes):
- `emotional_score` — moment intensity, peak human drama visible in the frame
- `social_score` — scroll-stop probability at thumbnail scale
- `identity_score` — fan belonging signal, team colors, player recognizability

Event-level `timeliness` is read from the `events` document (computed at ingestion — not scored per image).

In addition to the five scores, `score_assets_with_vision` emits a `detected_subjects: list[str]` per asset — the names of recognizable players/people visible in the frame (empty when none). This is the structural fix for the identity-blind-cosine concern (per D-026): Step 5's `propose_review_queue` composes `detected_subjects` against the narrative's `key_figures` to upweight identity-matched neighbors over generic-scene matches when assembling the exploitation queue.

Scores serve different purposes per queue: for the exploitation half, technical fitness is the quality gate that catches compositionally-similar-but-technically-unfit images; commercial signal provides ranking refinement. For the exploration half (assembled by `propose_review_queue`), technical fitness confirms the frame is viable and commercial signal indicates whether the image has qualities worth surfacing despite low similarity.

**5. `propose_review_queue`** — **The strategic decision.** Takes similarity results (from `find_similar_assets`), scores (from `score_assets_with_vision`), and narrative (from `build_event_context`); outputs the ranked review queue. Hard-refuses if any of those four preconditions are missing, with self-correcting errors that tell the agent what to call next.

The agent's reasoning shapes both halves of the queue:
- For exploitation, order surfaced items by event-narrative fit; attach per-item rationale.
- For exploration, select which non-similar items merit surfacing; attach per-item rationale ("this didn't match past winners but captures X — worth your time").

Each surfaced item's `queue_type`, `product_route`, **`queue_rank`, and `queue_rationale` are persisted onto the asset document** (not only returned in session state) — Step 6 reads them as copy substrate and the queue is re-renderable from MongoDB (D-029, D-022 persistence philosophy).

The **90% / 10%** exploitation/exploration ratio (§ Routing strategy) is the *expected emergent shape* of a typical event — it falls out of the similarity cutoff plus the agent's discovery selection. It is **not an enforced budget or cap**: the agent surfaces what merits the operator's time, which for a thin-similarity event (the demo's group-stage draw) is discovery-heavy by design (D-029).

This is where AI judgment beats heuristics.

**6. `draft_campaigns_for_queue`** — For each queued asset, generate a campaign draft using the event narrative from capability 2 as copy substrate:
- Headline and caption grounded in the specific event narrative angle — not generic copy
- Product specs and platform target derived from `product_route` (or the exploration item's per-item reasoning)
- Timing recommendation based on event `timeliness`
- Pushes all drafts to the approval queue with `status: "pending"`

The narrative is what differentiates *"Argentina beats France — World Cup 2026 poster"* from *"Messi ends France's reign in extra-time thriller — limited edition print."*

Handles the redraft case: when called with operator edit notes from a prior `request_human_approval` cycle, generates revised drafts informed by those notes. *(The redraft branch is **implemented in Step 7**, with the HITL loop that defines the `operator_notes` payload; Step 6 implements first-pass drafting and reserves the parameter — D-030.)*

**7. `request_human_approval`** — HITL via `LongRunningFunctionTool`. Suspends. Operator reviews the approval queue; for each item, decision is `approved`, `rejected`, or `edit_requested`. No execution occurs until this gate is passed.

When the tool resumes with decisions:
- All approved → agent calls `execute_approved_campaigns` on the batch
- Any rejected → those items drop; executable subset proceeds
- Any edit-requested → agent calls `draft_campaigns_for_queue` with the edit notes, then loops back to `request_human_approval`

The edit-requested loop is the agent's reasoning, not a separate capability. A revision cap (per `docs/safety-measures.md`) lives in the system prompt **and** the tool's contract to prevent infinite revision cycles (Gap 1 closed in Step 7 — D-031).

*(Resume mechanics — D-031.* The decisions arrive as a per-item **list keyed by `approval_id`** (`approved` / `rejected` / `edit_requested` + optional `reviewer_notes`). The `LongRunningFunctionTool` body does **not** re-run on resume — the payload goes to the coordinator LLM, which calls a separate `apply_approval_decisions` tool to persist the decisions; `execute_approved_campaigns` and the redraft path then re-read persisted state. The **redraft branch is implemented in Step 7** (closing the Step 6 / D-030 reservation): it reads persisted `edit_requested` approvals and overwrites the drafts. Capabilities 7/8 are coordinator-plane tools, not workflow nodes. Mixed batches resolve **resolve-then-execute** (redraft to resolution, then one execute over the accumulated approvals).)*

**8. `execute_approved_campaigns`** — For approved items:
- **Shopify:** create product draft via GraphQL Admin API
- **Printful:** initiate async mockup generation (`POST /mockups` → poll `GET /mockups/{task_id}`); polling is internal to this capability
- **Social:** write complete post package to MongoDB with `status: "queued"` (simulated — no live API call)

**9. `record_outcomes`** — For each published asset, a **provenance record** is written to the `performance` collection: true linkage (`asset_id` / `campaign_id` / `event_id`), the channels awaiting measurement, and the **7-day measurement window** anchored at publish time. **Metrics are left null/pending** (`metrics_status: "pending_sync"`) — they are populated **asynchronously by an external sync** (Shopify order webhooks / channel analytics) over the window, not fabricated at execution time. This is the **thin, honest coda** (D-032): it records that outcomes are *tracked and awaiting sync* without inventing a sale. On subsequent runs the corpus of *measured* exemplars grows, so similarity-grounded exploitation gets better-grounded over time without retraining — consumed via the **Step-2 historical baseline** (`build_event_context`), not via the `find_similar_assets` vector search (which never reads metrics). The external sync that populates the metrics, and a `get_top_performers_by_channel` analytics view, are the **enterprise path** (descope, not removal — capability 9 runs end-to-end).

---

## Demo Flow (Judge-Facing Narrative)

Two contrasting events demonstrate that the agent reasons strategically rather than running a fixed pipeline. Event 1 carries the full flow; Event 2 focuses on how the strategy differs. **Pacing target: ~3 minutes total.** Full pacing breakdown and reproducibility plan: `docs/strategic-agent-reframe.md` § Demo coherence.

### Event 1 — Upset victory at peak timeliness (~90 seconds)

Argentina vs. France 3–2 (or similar high-profile upset), match concluded ~20 minutes ago. `outcome_type: upset_victory`.

Full flow on screen:
- Ingest 30–50 photos + event metadata
- Build event context (narrative + `player_context` retrieval — MongoDB visible)
- Find similar assets (vector search — primary load-bearing MCP step, visible)
- Score assets (Gemini Vision)
- **`propose_review_queue` with per-item reasoning shown on screen — the strategic-agent moment**
- Generate campaign drafts
- HITL: operator scrolls the queue briefly, approves
- Execute: Shopify draft created, Printful mockup initiated, social post queued
- MongoDB collections populated

Expected agent strategy: rich exploitation queue (many similarity matches against historical-winner archetypes), narrow but pointed exploration picks (*"the candid bench-celebration shot did not match past winners but captures the disbelief — worth your time"*).

### Event 2 — Group-stage draw at moderate timeliness (~45 seconds)

A 1–1 group-stage match, ~2 hours post-final-whistle. `outcome_type: draw`.

Skip-ahead montage through ingest, context, similarity, scoring. Focus on **how queue assembly differs from Event 1**:
- Thin exploitation queue (similarity engine has few historical matches)
- Exploration emphasis — agent has to actively justify why anything is worth surfacing
- Different per-item reasoning, different queue shape

The contrast event — proves the agent reasons strategically rather than running a fixed pipeline.

### Closing (~15 seconds)

MongoDB final state across both events. Performance metrics. Title card with stack and partners.

The story is operational velocity *and* visible strategic judgment — not just "watch the workflow run"; "watch the agent decide differently for two different events."

---

## Judging Criteria Alignment

| Criterion | How we address it |
| --- | --- |
| Technological Implementation | MongoDB MCP load-bearing across all 9 capabilities — vector search in `find_similar_assets` (primary load-bearing call), reads/writes on `events`, `assets`, `campaigns`, `approvals`, `performance`, `player_context`; Gemini for narrative reasoning, vision scoring, and embeddings; Google ADK v2.1 hosting the strategic agent with HITL via `LongRunningFunctionTool` |
| Design | Clean approval UI showing per-item reasoning for every queued asset; operational dashboard showing capability composition and queue-assembly results; score profiles visible |
| Potential Impact | Real economic problem — sports commerce monetization windows; scales to any live event |
| Quality of the Idea | Strategic agent that composes capabilities into per-event campaign strategies — type-2 agentic value (judgment under bounded ambiguity), not procedural workflow enactment; grounded scoring via vector search; visible per-item reasoning |

---

## Success Metrics

- Time from event upload → approval queue populated (target: under 60 seconds for 50-image batch)
- **Queue-assembly coherence:** for a given event type, does the agent produce a queue whose composition matches expected strategy (per-event-type assertion class in trace evals, per `docs/evaluation-strategy.md`)
- Human approval rate on agent-surfaced candidates (both exploitation and exploration)
- Shopify draft creation success rate
- Printful mockup generation completion rate
- Demonstrability: the full capability composition runs end-to-end in a single demo session without errors; per-capability trace-eval pass rate ≥ 95% across 20 reps (D-020)
