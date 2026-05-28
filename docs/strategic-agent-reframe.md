# Strategic-Agent Reframe

Design resolution — captures a pivot in how this project frames the agent: from **procedural enacter of an 8-step workflow** to **strategist that assembles the operator review queue** for a given event, then executes against the approved queue.

Companion to `agentic-model.md` (which describes the pre-pivot shape) and a precursor to the spec edits this pivot requires.

---

## Why this pivot

The 8-step workflow shape we documented is workflow-shaped, not agentic-shaped. The agent's "planning" today amounts to re-deriving, every run, what we already wrote down in tool docstrings ("call X before Y"). That is not where agentic value lives.

There are two distinct sources of agentic value:

1. **Large exploration surface** — agent traverses unstructured space (Internet, codebase, document corpus). Value is *discovery*. Travel-booking and research agents fit here.
2. **Judgment under ambiguity in a small action space** — agent picks from a bounded action set, but which action fits *this* case is non-obvious and requires domain reasoning. Value is *judgment*. Triage doctors, editors-in-chief, sentencing judges fit here.

Our project is type 2, not type 1. We are not exploring the Internet. We are deciding "given this event, what is the right operator review queue?" The action space is bounded (we know the channels, scoring dimensions, asset routes); the right *composition* for a given event is not.

This also aligns the project more honestly with the hackathon mission — *"handle complex goals. Your agent should be able to plan the steps and use the tools at its disposal to finish the job, while keeping you in control"* — at the substantive level rather than only the cosmetic level.

---

## The resolved strategic surface

**One strategic decision: the agent assembles the operator review queue for this event.**

Everything else is mechanical or LLM-at-the-node-level. This is the agent's strategic job. Done well, it is enough.

### Anatomy of the queue-assembly decision

The agent's deliverable is *a ranked, reasoned queue tailored to this event*. It has two halves and one cross-cutting property:

**Exploration selection (the load-bearing half).** Per D-015, the exploration queue was originally random-sampled from non-exploitation assets. The reframe replaces random selection with agent judgment: from the set of assets that did *not* match past winners by similarity, the agent picks which ones are worth surfacing to the operator. This is the only place in the system where the agent has to reason without a deterministic crutch — no similarity signal, no past-performer template, just an image and the question *"is this worth the operator's time?"* That is the canonical judgment-under-bounded-ambiguity case.

**Exploitation ordering (the lighter half).** Similarity routing in Step 3 produces the top-K. The *order* in which they reach the operator is judgment — the agent can prioritize by event-narrative fit ("this event is the upset victory; surface the celebration shots first"), by reviewer workflow ("group the technically borderline ones together"), or by other domain reasoning. Without this, the exploitation queue is the similarity engine's raw output — which would undersell the system. The agent should leave its fingerprints on both halves of the queue, even if exploration is where it earns most of its keep.

**Per-item reasoning (cross-cutting).** For every item the agent surfaces — exploitation or exploration — it produces a one-sentence rationale for the operator. Exploitation items get "narrative fit" reasoning; exploration items get "why this is worth your time despite the miss" reasoning. This is not a separate decision; it is a property of the queue. It is also what makes the demo legible: the operator (and the judge) can read *why* an item is in the queue at all.

### Why this scope and not more

A broader set was considered and rejected — channel mix, scoring-weight selection, escalation. Each failed on a specific structural reason rooted in prior decisions:

| Originally proposed | Why it was wrong for MVP |
| --- | --- |
| Channel mix per event | Per-asset routing in Step 3 is *implied* by similarity to past winners (D-015). The agent isn't choosing the route; past performance is. A strategic mix either overrides similarity or is an emergent property of which assets surface. Either way, not a real decision. |
| Asset selection criteria (scoring weights) | Similarity is upstream of scoring. Within exploitation, similarity has already picked the candidates; scoring is mostly a quality gate plus tie-breaking. Re-weighting per event nudges rank order within an already-selected set — parameter tuning, not strategy. |
| Escalation (proceed / defer) | The two-queue design means there is *always* something to surface, even when similarity returns nothing strong. Proceed-or-defer at the event level collapses to "proceed" almost always — not a live decision. |

The common thread: **the existing spec already mechanized the strategic surface most of these would have occupied.** D-015 (two-queue split), D-016 (Step 2 narrative + player_context RAG), and the similarity-grounded routing of Step 3 collectively answer most of the "what to do" question deterministically before the agent gets a chance to reason about it.

**Queue assembly is the surface that survives the mechanization** — because the exploration queue is exactly where the existing spec admits it has no deterministic answer, and exploitation ordering is exactly where the existing spec stops short (similarity gives you the set, not the order to present them).

### Why not just exploration selection (one decision, not two halves)

Exploration selection alone is defensible — it is the high-judgment half, and it is where AI's value over heuristics is most demonstrable. Adding exploitation ordering is not a separate strategic decision; it is the same decision (queue assembly) reaching into the exploitation half rather than stopping at the exploration boundary.

If scope forces a cut, **exploitation ordering can collapse to "rank by score" and only exploration-selection remains the agent's call.** That is the documented fallback. The richer version (both halves) is the target.

### D-015 reconciliation

D-015's rationale for random sampling was *honesty preservation*: "Random is the maximally honest form of exploration: it cannot structurally exclude any candidate by definition." Agent-driven selection necessarily imposes structural exclusion — whatever criteria the agent uses.

The pivot is consistent with D-015's broader framing, not a reversal of its spirit. The D-015 spec itself names alternatives ("novelty-scored queue," "low-similarity tail," "diversity constraints") and frames them as configuration choices for different customers. The hackathon demo is one such configuration choice — agent-driven novelty selection — and random remains a valid fallback documented in the same place.

The new D-entry (forthcoming in `tracking.md`) should record this as: *"D-015's random-sampling default for exploration is superseded for the MVP demo by agent-driven novelty selection with per-image reasoning. Random remains the documented fallback configuration; the choice is presented to judges as a customer-tunable parameter, not a fixed design."*

---

## The capability surface

(Resolution to open question #2.)

The strategic decision (queue assembly) is one capability; the rest of the surface is the set of operations the agent composes to feed and consume that decision. This section resolves what those operations are, at what granularity, and what stays internal.

### Principle and granularity choice

A capability should be:

- **Coherent** — one purpose the agent can reason about in a sentence ("score these images," not "send a Vision API request and parse the response and write to MongoDB")
- **The right shape for the agent to compose** — chunky enough that the agent doesn't drown in micro-operations, not so chunky that strategic decisions get buried inside
- **A wrapper boundary that hides MCP and implementation detail** — per D-019, the agent sees domain operations, not raw MCP calls
- **Externally legible** — when a trace shows the capability fired, a human (operator, judge, future-us) can tell what just happened

Three levels of granularity were considered:

| Granularity | Capability count | Trade-off |
| --- | --- | --- |
| Fine (one wrapper per MongoDB op + per LLM call) | ~20+ | Maximum transparency; agent drowns in micro-operations; current Step 1 tool surface lives here |
| **Mid (one capability per current step boundary)** | **~8–9** | **Best fit — chunky enough to reason about, fine enough to be legible** |
| Coarse (bundle steps into super-capabilities) | ~3–5 | Hides too much; strategic surface gets buried inside `do_everything` |

Mid-granularity is the resolution. Internal wrappers are preserved as the implementation layer beneath each capability.

### The nine capabilities

| # | Capability | Kind | Notes |
| --- | --- | --- | --- |
| 1 | `ingest_event_batch(images, event_metadata)` | computational | Wraps current `compute_timeliness` + `record_event` + `record_assets`. The three Step 1 wrappers remain; they are not agent-facing tools. |
| 2 | `build_event_context(event_id)` | computational + LLM | Aggregates event, past performance, and player context; produces structured narrative (Step 2 output). |
| 3 | `find_similar_assets(event_id)` | computational | Embeds candidates + vector-searches `assets`. **Explicit, not implicit** — see argument below. |
| 4 | `score_assets_with_vision(event_id)` | computational + LLM | Runs Gemini Vision on each asset, writes 5-dimensional scores. Batch internally; one call, N images. |
| 5 | **`propose_review_queue(event_id)`** | **strategic — the one decision** | Takes similarity results + scores + narrative; outputs ranked queue with exploitation ordering, exploration selection, and per-item reasoning. Where queue assembly lives. |
| 6 | `draft_campaigns_for_queue(queue_items)` | LLM | Generates copy per queue item using the Step 2 narrative as substrate; creates campaign documents and approval records. Handles the redraft case (takes operator notes when present). |
| 7 | `request_human_approval(approval_batch)` | HITL — `LongRunningFunctionTool` | Suspends. Resumes with approved/rejected/edit_requested decisions per item. |
| 8 | `execute_approved_campaigns(approvals)` | external APIs | Shopify GraphQL + Printful REST + social-queue write. Internal retry on Printful mockup polling. |
| 9 | `record_outcomes(executed_campaigns)` | computational | Step 8 — writes `performance` documents. |

Nine capabilities, mapping roughly to the eight current steps with `propose_review_queue` carved out as the new strategic surface (which is what makes the reframe a reframe).

### Explicit similarity (and explicit scoring) — not bundled into queue assembly

The biggest sub-question inside #2 was whether `find_similar_assets` and `score_assets_with_vision` should be hidden inside `propose_review_queue` (queue assembly "is" similarity + judgment composed) or remain explicit capabilities the agent invokes separately. **Resolution: explicit, not implicit**, for three reasons in priority order:

1. **MongoDB partner-track demo legibility.** Vector search is explicitly called *"the primary load-bearing MCP step"* in `02-architecture.md`. Burying it inside a higher-level capability hides the partner integration that is load-bearing for judging. A judge skimming a trace should see `find_similar_assets → returns top-K with scores → propose_review_queue uses those + judgment`. That trace tells the MongoDB story. The implicit version tells "queue assembly happened somehow."

2. **Separation of computation from judgment.** `find_similar_assets` is deterministic (same inputs → same outputs). `propose_review_queue` is the agentic decision. Keeping them separate is honest about where AI value lives — judgment is composed *on top of* computation, not entangled with it. Easier to eval, easier to reason about, easier to swap (e.g., if we change embedding models, only one capability changes).

3. **Reusability for other reasoning.** The agent may want to call similarity for purposes other than queue assembly — e.g., when contextualizing an event, finding past events with similar narratives. Making similarity a primitive capability keeps that door open without forcing every consumer through queue assembly.

The case for implicit reduces to *"composition doesn't require hiding the components."* The agent calls similarity, observes results, then calls queue assembly with those results as input. The composition is visible at the trace level, not collapsed into one opaque call.

The same argument applies to `score_assets_with_vision`: keep it explicit for the same three reasons. Queue assembly consumes scores; it does not run Vision internally.

### What is not in the surface

The principle: **if a tool exists only as plumbing for another capability, it stays internal.**

- **Raw MongoDB MCP operations** — never exposed (D-019).
- **`compute_timeliness` as its own agent-facing tool** — folded into `ingest_event_batch`. Stays as a Python wrapper for unit testing; the agent does not see it. This is a small departure from the Step 1 plan, which exposes it as a `FunctionTool` — reconciliation lives in the propagation plan.
- **Per-collection getters** (`get_event`, `get_assets_for_event`, etc.) — internal to whichever capability wrappers need them. Not agent-facing.
- **Printful mockup polling** — internal to `execute_approved_campaigns`. The agent does not poll.
- **Direct Vision API calls** — internal to `score_assets_with_vision`.
- **Embedding generation** — internal to `find_similar_assets`. The agent never sees a 3072-dim vector.

Agent-facing surface is the set of operations the agent has reason to compose at the strategic level. Plumbing is plumbing.

### Batch vs. per-item iteration

Capabilities that operate over N items (`score_assets_with_vision`, `draft_campaigns_for_queue`, `execute_approved_campaigns`) take a batch as input and handle iteration internally. The agent passes "score all assets for this event" and gets back batch results — it does not loop over N images making N tool calls. This matters for:

- **Token efficiency** — one tool-call round-trip vs. N
- **Trace legibility** — one event per capability vs. N events
- **Eval simplicity** — assertions on one batched outcome vs. N items

The exception is `propose_review_queue`: its *input* is one invocation, but its *output* is per-item (queue items with per-item reasoning). That is the per-item surface the operator and demo see.

### HITL shape

`request_human_approval` is the only `LongRunningFunctionTool`. It takes the full approval batch and returns the full decision batch — the agent does not await one approval at a time. After it resumes:

- **All approved** → agent calls `execute_approved_campaigns` on the full batch
- **Any rejected** → those items drop; executable subset proceeds
- **Any edit-requested** → agent calls `draft_campaigns_for_queue` with the edit notes, then loops back to `request_human_approval`

The edit-requested loop is the agent's reasoning, **not a separate capability**. Same `draft_campaigns_for_queue` tool, different input. The revision cap from `safety-measures.md` lives in either the system prompt or in `request_human_approval`'s contract (e.g., the tool refuses further edit cycles after N rounds and forces approve-or-reject). That choice is downstream of this resolution.

### Alternatives considered and rejected

- **Bundle `find_similar_assets + score_assets_with_vision + propose_review_queue` into one `analyze_and_propose_queue` capability.** Rejected: loses MongoDB visibility (argument 1 above) and entangles computation with judgment (argument 2). The case "fewer tools = simpler agent surface" loses to the fact that 8–9 capabilities is already simple.
- **Fold `record_outcomes` into `execute_approved_campaigns` as a post-step.** Rejected: feedback-loop legibility in the demo. "Watch the system record outcomes for the published campaigns" is a discrete demoable moment. Bundling it into execute hides it.
- **Expose `compute_timeliness` as its own agent-facing tool.** Rejected: timeliness is a pure formula the agent has no business reasoning about. Folding it into ingestion is the right abstraction. The Step 1 plan exposes it as a tool today, which is the small departure flagged above.

---

## Enforced vs. emergent (revised by D-024)

(Resolution to open question #3.)

The capability surface defines *what* the agent can do; this section resolves *what each capability enforces* and what stays in the agent's discretion. The pre-D-024 principle was: **enforce data dependencies via wrapper-level `PreconditionError`; leave order among independent operations to the agent.** D-024 tightened the enforcement surface: order is now enforced **structurally by workflow graph edges**, not by `PreconditionError` checks at runtime. `PreconditionError` remains as a defense-in-depth signal — direct capability calls (e.g., from unit tests in `tests/test_step_*.py`) still get the self-correcting error if state is missing — but the graph removes the surface for the agent to violate the dependency in the first place.

### Why this split

Data dependencies are physical invariants — you cannot propose a queue with no assets, draft for a non-existent queue, or execute approvals that do not exist. Pre-D-024 these were enforced at the wrapper layer; post-D-024 they are enforced at the workflow-graph layer, with the wrapper-layer check kept as a safety net. Either way, agent autonomy gains nothing from being free to try them and fail.

Order among independent operations was originally framed as judgment-shaped: among `build_event_context`, `find_similar_assets`, and `score_assets_with_vision`, all three only require ingestion and all three feed `propose_review_queue`. **D-024 reframes this**: since the agent's value at Layer 2 (capability composition) is recognition rather than judgment (see `agentic-model.md`), the marginal value of letting the agent pick an order among independent operations is small, while the cost of letting it skip a step or hallucinate an order is real. The workflow graph wires them as a fixed chain. The agent's strategic surface stays exactly where it was — on `propose_review_queue` (Layer 3).

This still matches D-019's spirit: wrappers enforce data contracts; the agent's strategic surface lives above those contracts. The change is that the agent no longer drives composition at all (the graph drives it); the strategic surface — Layer 3 — is unchanged.

### Preconditions per capability

| Capability | Hard preconditions (enforced) | Notes |
| --- | --- | --- |
| `ingest_event_batch` | none | Always first |
| `build_event_context` | event exists | Independent of similarity / scoring |
| `find_similar_assets` | event + assets exist | Independent of context / scoring |
| `score_assets_with_vision` | event + assets exist | Independent of context / similarity |
| **`propose_review_queue`** | **event + assets + similarity results + scores + narrative (all four)** | See argument below |
| `draft_campaigns_for_queue` | queue exists (returned by `propose_review_queue`) | |
| `request_human_approval` | drafts exist (returned by `draft_campaigns_for_queue`) | |
| `execute_approved_campaigns` | approvals with `status: approved` exist | |
| `record_outcomes` | execution complete | |

The middle three (`build_event_context`, `find_similar_assets`, `score_assets_with_vision`) have no order constraint among themselves. The agent picks. The system prompt can suggest a typical order without enforcing it.

### `propose_review_queue` enforcement — hard-refuse with informative errors

The specific sub-question in #3 was whether `propose_review_queue` should hard-refuse when prerequisites are missing, or return a soft signal that the agent reasons about. The framing as binary was incomplete. The right answer is **hard-refuse with an informative error that tells the agent what to call next** — neither silent refusal nor partial-result soft-signal.

Example shape:

```python
propose_review_queue(event_id="wc2026-match-42")
→ raises PreconditionError:
  "Cannot propose review queue for wc2026-match-42:
   - scores not found (call score_assets_with_vision first)
   - similarity results not found (call find_similar_assets first)"
```

The agent reads the error, calls the prerequisites, retries. No degraded queue, no ambiguous "queue was empty because scores were missing" demo footage.

**Why all four preconditions, not a subset.** The temptation is to let `propose_review_queue` run with partial inputs — *"if scores are missing, propose a queue without scoring-based reasoning."* Don't do this in MVP:

- **Demo coherence demands full inputs.** Both planned demo events produce strategy-rich queues with full reasoning. Degraded fallback queues would weaken the demo, not enrich it.
- **Eval surface stays clean.** *"Agent called all prerequisites before queue assembly"* is one assertion; *"agent called the right subset for the strategy it pursued"* is harder and fuzzier.
- **The arguments for partial inputs are speculative.** *"More agentic"* and *"handles partial failures"* are hypothetical benefits. Hard-refuse is concrete and matches the other wrapper-discipline patterns we have.

The production path could relax this — *"if scoring partially fails, propose queue from the assets that did score."* That is enterprise-path. For MVP, full preconditions.

**Why error messages should self-correct.** Three reasons:

1. **Recovery latency.** Without a hint, the agent has to reason *"what does `propose_review_queue` need? Let me re-read the system prompt..."* With a hint, it calls the named prerequisite immediately.
2. **Token efficiency.** Each unproductive reasoning round costs tokens. The error is a cheap nudge.
3. **Eval debuggability.** A trace that shows *"raised PreconditionError → called X → retried"* has a legible failure mode. A trace that shows *"raised PreconditionError → wandered → eventually figured it out"* has a muddier diagnostic story.

Consistent with how good library error messages work — not `ValueError` but `ValueError: expected 'foo', got 'bar' (did you mean to pass --foo?)`.

### What stays emergent

Three concrete agent surfaces are protected from over-constraint:

1. **Order among the three independent operations.** Agent picks whether to build context first, find similar assets first, or score first. No constraint, no penalty.
2. **How to compose the queue strategically.** Queue assembly itself is the strategic decision — agent decides ratios, ordering, which exploration items merit surfacing, what reasoning to attach.
3. **Whether (and how many times) to redraft after edit-requested.** Per the HITL shape in § The capability surface, the edit-requested loop is agent reasoning, not a separate capability. The safety-measures cap (max N rounds) is the only constraint.

These are the agentic surfaces. They are deliberately not enforced.

### Softer enforcement considered

One pushback worth naming: *"Hard-refuse on all four preconditions is too rigid — what if the agent wants to skip context-building because the event has no narrative-interesting outcome (e.g., a 0-0 draw)?"*

The right answer is **capabilities run; agent reasons about outputs.** `build_event_context` should still run even for boring events — it returns *something* (even if narrative angle is `"none of note"`). The agent reading that output then chooses how much weight to give narrative in queue reasoning. The capability runs always; what the agent does with its output varies.

Skipping a capability because its output is expected to be boring is premature optimization that defeats the determinism we are trying to preserve.

---

## Demo coherence

(Resolution to open question #4.)

The hackathon deliverable is a ~3-minute video. "Demo coherence" is the discipline of making that video legible, reliable, and load-bearing for the strategic-agent reframe — not just a happy-path screenshot reel.

### What the demo must accomplish

1. **Demonstrate the strategic-agent reframe.** Otherwise the pivot we just made is invisible to judges. Agent reasoning has to be on-screen; queue assembly has to be the centerpiece; per-item reasoning has to be readable.
2. **Show MongoDB MCP as load-bearing.** Partner-track requirement. Vector search visible in the flow; collection state visible before and after.
3. **Include HITL.** *"Keeping you in control"* is hackathon spec language. The demo cannot skip it.
4. **Run reliably enough to record without excessive takes.** Our 95% pass-rate eval discipline gives roughly 5–8 takes to get a good one. That is the budget.
5. **Be legible to a judge who has not read our specs.** Captions, voiceover, on-screen labels for what the agent is doing right now.

### Threats to coherence

| Threat | Concrete failure mode | Mitigation |
| --- | --- | --- |
| Run-to-run LLM variability | Different queue compositions or reasoning text across takes | Rely on 95% pass-rate; record multiple takes and curate |
| Within-run strategic variability | Agent under-surfaces or over-surfaces queue items | System prompt nudges toward "surface meaningful work"; eval covers this |
| Time budget | 3 minutes is tight for two full event runs | Event 1 full flow, Event 2 strategic-differences only |
| External API flake (Shopify, Printful) | Demo crashes mid-record | Wrapper-level retry; pre-validated dev store + Printful account; rehearsal day-of |
| Asset corpus mismatch | Agent surfaces only 2 items because the corpus does not support a rich queue | Asset curation is offline work — pick corpus deliberately for each demo event |
| Judge does not understand what is happening | Video shows tool calls flying by; judge cannot read them | On-screen labels, captions, voiceover explaining each phase |
| HITL feels fake | Demo human approves instantly without reviewing | Show the operator scrolling the queue briefly, then approving — adds 5 seconds, conveys real review |

The first three are addressable through process (eval discipline, asset curation, pacing). The last four are addressable through production choices made during filming.

### The demo shape

**Two contrasting events. Event 1 full flow; Event 2 strategic-differences only.**

Why two events, not one: the strategic-agent reframe is the entire point of the pivot. A single-event demo can show *that* the agent reasons strategically, but only contrast shows *how* it reasons differently across events. That is the load-bearing evidence that AI judgment beats a procedural workflow.

Why not three: 3-minute budget. Two events with the proposed pacing already cost ~2:30; three would leave no room for setup, closing, or breathing.

### Recommended pacing breakdown

| Time | Phase | What is shown |
| --- | --- | --- |
| 0:00–0:15 | Setup | *"Sports commerce monetization windows close fast. Watch the agent turn a match-day photo batch into approved campaigns."* Quick UI screen showing MongoDB collections empty. |
| 0:15–1:45 | **Event 1 — Upset victory** | Full flow. Ingest → context → similarity (MongoDB MCP visible) → scoring → **queue assembly with per-item reasoning shown on screen** → draft generation → HITL (operator scrolls, approves) → execution → MongoDB collections populated. |
| 1:45–2:30 | **Event 2 — Group-stage draw** | Skip-ahead montage of ingest/context/score/similarity. Focus on **queue assembly: how the strategy differs from Event 1**. Side-by-side comparison if possible. Thin exploitation queue, agent justifying exploration picks. |
| 2:30–2:50 | Closing | MongoDB final state across both events. Performance metrics. |
| 2:50–3:00 | Title card | Stack, partners, links. |

The strategic-agent moments are at roughly 1:00–1:30 of Event 1 and 2:00–2:20 of Event 2. Those are the load-bearing seconds. Everything else is scaffolding.

### The two events

- **Event 1 — Upset victory at peak timeliness.** Argentina vs. France 3–2 (or similar high-profile upset), match concluded ~20 minutes ago. `outcome_type: upset_victory`. Expected agent strategy: rich exploitation queue (many similarity matches against historical-winner archetypes), narrow-but-pointed exploration picks (*"the candid bench-celebration shot did not match past winners but captures the disbelief — worth your time"*). Drama, momentum, immediate commercial potential.
- **Event 2 — Group-stage draw at moderate timeliness.** A 1–1 group-stage match, ~2 hours post-final-whistle. `outcome_type: draw`. Expected agent strategy: thin exploitation queue (similarity engine has few historical matches), exploration emphasis, agent has to actively justify why anything is worth surfacing. May include a *"recommend defer on the merch side"* element if that emerges from the strategic surface. The contrast event — proves the agent reasons strategically rather than running a fixed pipeline.

The emotional arc of the demo is the contrast between these two events. Per-item reasoning is the throughline.

### Asset corpus curation

Per event, ~30–50 Wikimedia Commons photos, curated offline before recording:

- **For Event 1:** must include several photos that visually resemble historical-winner archetypes (so the exploitation queue is rich) PLUS at least 2–3 interesting outliers the agent might surface as exploration picks.
- **For Event 2:** must include photos that produce weak similarity matches (so the exploitation queue is genuinely thin) PLUS photos that have *something* worth saying about them despite the miss.
- Photos seeded into `assets` with synthetic `performance` data so similarity search has past winners to match against — this is already required by the architecture; demo curation is a specific selection within that.

This is a tracked deliverable; it lives in a future `docs/plans/demo-corpus.md`, not in this design doc.

### What is deferred to production

Some demo-coherence questions are unanswerable until there is a working end-to-end system to film against:

- **Exact voiceover and captions** — post-implementation, when we know what is actually on screen.
- **Final asset corpus selection** — depends on what queue shapes the implemented agent produces with various corpora.
- **Recording technical choices** — screen capture vs. composited; code overlay vs. UI overlay; etc.

These are production decisions, not design decisions. The design commitment here is *"two contrasting events, Event 1 full flow + Event 2 strategic-differences."* Production fills in the rest.

### Alternatives considered

- **One event with a deeper dive.** Rejected: 3 minutes lets a single event breathe, but losing cross-event contrast loses the single strongest evidence of strategic reasoning. The two-event contrast is the demo's most defensible piece.
- **Three events for more variation.** Rejected: 3-minute budget. Three events × even 50 seconds each = 2:30 with no room for setup, closing, or breathing.
- **All-pre-baked demo (no live LLM calls).** Rejected: hackathon judges weight authenticity. Pre-baked traces look like screenshots, not live behavior. Live with curated corpus and multiple takes is more honest.

---

## Step 1 reconciliation

(Resolution to open question #5.)

The reframe needs to land against work that is partly underway. Ground truth first, then the reconciliation plan.

### Ground truth

Step 1 has a committed plan (`docs/plans/step-1-event-ingestion.md`) and committed task list (`docs/tasks/step-1-tasks.md`) describing the pre-reframe approach (three atomic `FunctionTool`s: `compute_timeliness`, `record_event`, `record_assets`). **No Step 1 implementation code has been written** — `src/` contains only Step 0/0.5 foundation (`agent.py`, `prompt_loader.py`, `db/client.py`); `tests/` contains only `test_foundation.py`; no `tests/evals/` directory exists.

Reconciliation is a doc rewrite, not a code revert. Nothing in `src/` reverts.

### What "doing it right" means here

Three concrete commitments:

1. **The agent's first capability matches the reframed surface.** `ingest_event_batch` is the single agent-facing tool. The wrappers (`compute_timeliness`, `record_event`, `record_assets`) survive as internal Python functions used by the capability.
2. **The trace eval premise matches the reframed semantics.** Outcome-shaped assertions (what got written to MongoDB, with which fields), not sequencing-shaped (which tool fired in which order). The sequencing question collapses when there is one tool.
3. **The system prompt is not pre-emptively procedural.** Even though Step 1 only registers one tool, the prompt is the strategist framing — what evolves between steps is the registered toolset, not the prompt's framing. Staged-per-step prompts would undermine the evals.

### Three-phase plan

The strategic-agent reframe's propagation plan is the upstream context; Step 1 reconciliation is one item within it. Here is the dependency-aware execution order:

**Phase A — Propagate the reframe (blocking Step 1 implementation).** Spec edits, CLAUDE.md, tracking D-entry, v2 prompt, agentic-model.md, evaluation-strategy.md. Detailed in § Propagation plan.

**Phase B — Step 1 doc rewrites (the #5-specific work).** Rewrite `docs/plans/step-1-event-ingestion.md` and `docs/tasks/step-1-tasks.md` against the new design.

**Phase C — Implementation.** Execute the rewritten task list against the new design. `PreconditionError` foundation class lands here as part of Step 1 work.

### What survives, what rewrites in the Step 1 task list

| Task | Pre-reframe purpose | Post-reframe disposition |
| --- | --- | --- |
| T-1.1, T-1.2 | `Event` and `Asset` Pydantic models | **Survive intact** |
| T-1.3 | Conftest helpers returning Pydantic instances | **Survive intact** |
| T-1.4 | Timeliness calculator (pure function) | **Survive intact** |
| T-1.5 | Lazy `get_client()` accessor | **Survive intact** |
| T-1.6 | `record_event` as `FunctionTool` | **Keep as internal Python wrapper; not a `FunctionTool`** |
| T-1.7 | `record_assets` as `FunctionTool` | **Keep as internal Python wrapper; not a `FunctionTool`** |
| T-1.8 (was) | Register three `FunctionTool`s in `all_function_tools` | **Replaced — register only `ingest_event_batch`** |
| T-1.9 | Auto-wire in `build_agent()` | **Survives shape; new content (the one capability)** |
| T-1.10 | Eval scaffolding (`tests/evals/conftest.py`) | **Survives mostly intact — helpers are capability-agnostic** |
| T-1.11 (was) | Sequencing-shaped single-run trace eval | **Rewritten — outcome-shaped (see below)** |
| T-1.12 | Pass-rate eval at N=20 | **Harness unchanged; asserts against new eval premise** |
| T-1.13 | Full suite green | **Unchanged shape** |
| **New T-1.x** | `ingest_event_batch` capability itself | **New — wraps `compute_timeliness` + `record_event` + `record_assets` internally** |
| **New T-1.y** | `PreconditionError` class (foundation) | **New — see sub-decision below** |

The new trace eval shape:

> Given an operator prompt like *"We just finished Argentina vs France 3–2. Photos are in /tmp/wc-final/. Match started 19:00 UTC, finished ~20 min ago. Get them into the system,"* assert that (a) `ingest_event_batch` was called exactly once, (b) the event document sent to MongoDB has the correctly-extracted fields (teams, kickoff_utc, outcome_type), (c) timeliness was computed correctly internally, (d) N assets were written with `status="ingested"`, (e) the agent stopped (terminal text turn) after the capability returned, (f) reasoning text is present for the tool call.

Sequencing collapses to "called once." Outcome assertions strengthen — the field-extraction quality of the agent's natural-language parsing is now what we are testing, alongside the agent's coherence in stopping after success.

### Sub-decisions

**Should `PreconditionError` land in Step 1?** `ingest_event_batch` has no preconditions (always first), so technically the class is not needed yet. But establishing the pattern early is cheaper than retrofitting it when `propose_review_queue` arrives later. The class is small (~10 lines), and `ingest_event_batch` itself can use it for input validation (*"missing required field 'outcome_type' in event_metadata"*) — giving the pattern a real first usage to validate against. **Decision: yes, land in Step 1 as foundation work.** Added as a new task in the rewritten task list.

**v1 vs. v2 prompt timing?** Options were (a) land v2 prompt in Phase A even though only one tool is registered, or (b) defer v2 to when more tools exist. **Decision: (a).** The strategist framing is stable across the capability surface; what evolves is which tools are registered (which the agent reads from tool docstrings). Pre-staging v2 with one tool is honest — the agent is *"a strategist who currently only has the ingest capability available."* Forward-compatible; no mid-project prompt rewrite.

**Should the committed Step 1 plan/task docs be reverted, or updated in place?** **Updated in place.** They are committed but they are the active working docs for this branch. The rewrite commit message (*"Reframe Step 1 plan to match strategic-agent surface"*) becomes the paper trail.

### Softer approaches considered

- **"Land current Step 1 as-is, then refactor to the reframe after Step 1 ships."** Rejected:
  - The current trace eval would be sequencing-shaped (3-tool order); after the refactor it becomes meaningless and gets rewritten anyway. We would ship code we then unship.
  - An agent registered with 3 atomic tools builds operator intuition (*"the agent shows you the orchestration steps"*) that we would then break when collapsing to 1 capability.
  - The reframe's value comes from doing it consistently from the start. Half-reframed Step 1 is not a useful artifact.
- **"Keep all three FunctionTools registered alongside `ingest_event_batch` for flexibility."** Rejected: violates the capability-surface principle from § The capability surface (plumbing stays internal; mid-granularity means one capability per intent). The agent would have four ways to ingest, three of which are wrong.

---

## What changes, what stays

### Stays (foundation reusable, more than originally implied)

- MongoDB schemas, collections, domain wrappers — the data layer is unchanged
- D-019 enforcement, `MongoMCPClient`, the wrapper-vs-raw-MCP discipline
- ADK as framework, HITL via `LongRunningFunctionTool`
- Step 0 / 0.5 foundation, Pydantic models, prompt loader, lazy client accessor
- Tech-stack hard constraints (MongoDB partner, Gemini, embedding model, etc.)
- All domain content in the specs (player_context, scoring dimensions, what timeliness means, the 7-day performance window, the channel matrix)
- The 8 capabilities themselves — ingest, contextualize, similarity-search, score, draft, approve, execute, record-metrics — all remain LLM-using-tools at the node level
- The two-queue exploration/exploitation split from D-015 — its *structure* persists; only the exploration-queue's *selection mechanism* changes
- The narrative-driven copy generation in Step 5 — narrative still comes from Step 2; copy still uses it
- Hard constraints around tech stack

### Changes

- **Framing across `docs/specs/`** — from "8-step workflow" to "8 capabilities + one strategic decision (queue assembly)." `01-requirements.md` and `02-architecture.md` both lead with the step model and both need restructuring at the spec-layer.
- **Agent's tool surface** — collapses from ~20 micro-operations to 9 mid-granularity capabilities. See § The capability surface for the resolved list. The strategic call is `propose_review_queue`; all other capabilities are computational, LLM-at-the-node, HITL, or external-API in kind.
- **Exploration-queue selection mechanism** — replaces random sampling with agent judgment (per the D-015 reconciliation above).
- **System prompt** — strategist framing focused on queue assembly. Roughly: *"Given this event and its assets, ingest and contextualize, then propose a ranked operator review queue with per-item reasoning. Use similarity for exploitation candidates; use your judgment for exploration candidates. Get human approval before publishing."*
- **Hard constraint #1 in `CLAUDE.md`** — *"Do not simplify or merge the 8-step workflow"* was written assuming workflow-as-orchestration. Needs to be reframed as *"Do not remove capabilities or collapse the queue-assembly decision into a heuristic."*
- **Eval shape** — the load-bearing new assertion class is *queue-coherence*: did the agent assemble a queue whose composition makes sense for this event class (per-event-type expectations), and does each surfaced item have legible reasoning? Pass-rate discipline stays; the failure-category set in `evaluation-strategy.md` gains *strategy coherence*.
- **`agentic-model.md`** — describes the *pre-pivot* agent as a single LlmAgent enacting an implicit workflow. The implicit workflow remains for the non-strategic capabilities; the strategic surface (queue assembly) becomes the doc's primary subject for "where does the agent earn its keep." Doc needs revision.
- **Step 1's framing** — still "ingest," still typically the first capability invoked, but no longer "step 1 of 8." It is one capability the agent invokes in service of the queue-assembly goal.

---

## Remaining open design questions

(All five design questions are resolved by the sections above. Execution is now propagation, not design.)

1. ~~Strategic-decision scope~~ — **resolved: one strategic decision = queue assembly (exploration selection + exploitation ordering + per-item reasoning).**

2. ~~Capability surface design~~ — **resolved: 9 mid-granularity capabilities; `find_similar_assets` and `score_assets_with_vision` explicit (not bundled into queue assembly); plumbing stays internal. See § The capability surface.**

3. ~~What is enforced vs. emergent~~ — **resolved: enforce data dependencies as hard-refuse with informative errors; leave order among independent operations to the agent. See § Enforced vs. emergent.**

4. ~~Demo coherence~~ — **resolved: two contrasting events (upset victory + group-stage draw); Event 1 full flow, Event 2 strategic-differences only; ~3-min pacing; reproducibility via 95% pass-rate + multiple takes + curated asset corpus. See § Demo coherence.**

5. ~~Step 1 in-flight work reconciliation~~ — **resolved: no Step 1 code exists yet; doc rewrite only; three-phase plan (propagate reframe → rewrite Step 1 docs → implement, with `PreconditionError` foundation landing in Phase C). See § Step 1 reconciliation.**

---

## Propagation plan

Once this resolution is reviewed and stable, propagate in three phases. Phase ordering is dependency-aware — Phase A must land before Phase B/C so the source of truth is consistent for anyone reading docs or writing code.

### Phase A — Propagate the reframe (blocking Step 1 implementation)

1. **`tracking.md`** — add the pivot D-entry. Includes: procedural → strategic agent framing; queue assembly as the one strategic decision; D-015 reconciliation (random → agent-driven for the demo, random retained as fallback config).
2. **`docs/specs/01-requirements.md`** — restructure from "8-step workflow" to "8 capabilities + queue-assembly strategy." Keep the demo flow (refresh with the two-event contrast in § Demo coherence), success metrics, MVP non-goals. The exploration-queue section specifically needs editing to reflect agent-driven selection.
3. **`docs/specs/02-architecture.md`** — replace the workflow diagram with a capability surface diagram. Keep the MongoDB schemas, MCP call list, external integrations sections (data layer unchanged). The ADK Agent Architecture section needs revision — the implicit workflow framing goes away.
4. **`CLAUDE.md`** — revise Hard Constraint #1; update the Spec Documents table descriptions if they describe the workflow; update the "Current Phase" line if appropriate; ensure the `agentic-model.md` cross-reference still reads correctly after that doc's revision.
5. **`docs/agentic-model.md`** — rewrite the "what kind of agent this is" framing. The exit-conditions analysis mostly still applies (same single `LlmAgent`, same loop shape). The "8 steps as emergent property" framing should be replaced with "queue assembly as the strategic surface; other capabilities as bounded LLM-at-the-node tasks."
6. **`prompts/v2/agent_system.md`** — new prompt with strategist framing focused on queue assembly. No capability inventory in the prompt — the agent reads available tools from registered docstrings. v1 stays on disk for traceability; v2 is what gets registered going forward.
7. **`docs/evaluation-strategy.md`** — add the *strategy coherence* failure category; refresh examples to reflect queue-coherence assertions rather than tool-sequencing assertions for non-ingestion steps.

### Phase B — Step 1 doc rewrites (against the new design)

Rewrite `docs/plans/step-1-event-ingestion.md` and `docs/tasks/step-1-tasks.md`. See § Step 1 reconciliation for the full survives-vs-rewrites table. Headline changes: replace the 3-FunctionTool framing with the single `ingest_event_batch` capability; preserve T-1.1–T-1.5 intact; rewrite T-1.6 onward; add new tasks for `ingest_event_batch` itself and the `PreconditionError` foundation; shift the trace eval from sequencing-shaped to outcome-shaped.

### Phase C — Implementation

Execute the rewritten Step 1 task list. The `PreconditionError` foundation class (~10 lines, lives in `src/errors.py` or similar) lands as part of this work — first usage is `ingest_event_batch`'s input validation, establishing the self-correcting message format (cap → *"Cannot do X for Y: missing Z (call Z-producer first)"*) before later capabilities need it.

### Independent (not blocking A/B/C, but tracked)

Create `docs/plans/demo-corpus.md` — new doc capturing the asset-curation strategy per § Demo coherence. Per-event lists of ~30–50 Wikimedia Commons photos with rationale for inclusion (exploitation-archetype matches vs. interesting outliers). Tracked as a deliverable; offline work that happens before the first demo recording. Not blocking implementation; blocking the demo video.

---

## What this is not

- **Not a pivot of the problem.** The domain stays: real-time event commerce, sports merchandise monetization windows, MongoDB-grounded similarity. Judging-criteria fit for "real economic problem / potential impact" is preserved.
- **Not a framework change.** ADK + MongoDB MCP + Gemini stack unchanged.
- **Not a tear-up of existing code.** Foundation is reusable; the change is in framing, surface design, prompt, eval premise — not in wrappers, models, or data layer.
- **Not a reversal of D-015.** D-015's two-queue structure is preserved. Only the exploration-queue's selection mechanism changes from random to agent-driven, which D-015 itself frames as a configuration choice. Random remains the documented fallback.
- **Not an expansion of MVP scope.** One strategic decision is *less* than the original 8-step framing implied. The agent's surface narrows even as its substance deepens.
- **Not "every step is strategic."** Most capabilities remain LLM-at-the-node-level (bounded, LLM-using-tools). Agentic-strategic-ness lives in queue assembly. That is enough; it does not need to be everywhere.

---

## Cross-references

- `docs/agentic-model.md` — describes the pre-pivot agent shape; will be revised
- `docs/safety-measures.md` — loop bound + spend bound concerns; carry over unchanged
- `docs/testing-model.md` — three-category test model; categories unchanged, but eval surface within Category 3 gains the strategy-coherence assertion class
- `docs/evaluation-strategy.md` — remediation playbook stays; failure-category set gains *strategy coherence*
- `CLAUDE.md` § Hard Constraints — Constraint #1 needs revision after this pivot lands
- `tracking.md` — new D-entry to be added capturing the pivot rationale and D-015 reconciliation
- `tracking.md` D-015 — two-queue exploration/exploitation split, whose exploration default is updated by this pivot (not reversed)
- `tracking.md` D-016 — Step 2 event narrative + player_context RAG; unchanged but now serves the queue-assembly job specifically
