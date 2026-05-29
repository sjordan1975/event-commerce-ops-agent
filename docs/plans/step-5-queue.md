# Step 5 — `propose_review_queue`: Implementation Plan

## Context

Step 5 delivers `propose_review_queue` — **the one strategic decision** in the system (D-021). Every capability through Step 4 is deterministic or LLM-at-the-node (bounded reasoning producing a fixed artifact). Step 5 is where the AI earns its keep: given the event narrative, similarity results, and Vision scores already computed upstream, it assembles a *ranked, reasoned operator review queue* split into two halves — **exploitation** (order the similarity-matched winners by narrative fit) and **discovery** (select which non-matching images are worth the operator's time, and say why) — with a one-sentence rationale on every surfaced item.

This is the first — and only — node in the workflow graph that is a genuine **`LlmAgent(mode='single_turn')`** rather than a `FunctionNode` calling an internal LLM helper. That distinction is deliberate and load-bearing (see § Architecture decision below). Steps 2 and 4 also call the LLM, but as bounded node-internal helpers; making Step 5 a first-class agent node is the only thing that structurally separates "the one place judgment lives" from "the nodes that merely use the LLM as a tool." This is the project's central thesis encoded in the architecture, not in a comment.

Prerequisite: Step 4 (`score_assets_with_vision`) is merged to `main`. The graph is `START → ingest_event_batch → build_event_context → find_similar_assets → score_assets_with_vision`. Step 5 extends it with three nodes: a mechanical `prepare_queue_candidates` `FunctionNode`, the strategic `propose_review_queue` `LlmAgent` node, and a `persist_review_queue` `FunctionNode`.

---

## Architecture decision: in-graph `LlmAgent` node (validated by spike)

`02-architecture.md` (lines 353, 386) specifies `propose_review_queue` as an in-graph `LlmAgent(mode='single_turn')` node. Steps 2–4 established a *different* proven pattern (`FunctionNode` + internal `genai` structured-output call, e.g. `_run_narrative_llm`, `_score_asset_with_vision`). Before committing the plan to the spec-literal path, the ADK mechanics were de-risked exactly as D-024 was — via a spike (`spike/adk_llm_node_queue_spike.py`).

**Spike verdict: PASS on both mocked and live paths.** The four Step-5-specific unknowns D-024's spike left open are all validated:

| Claim | Mechanism proven |
| --- | --- |
| State → prompt | `instruction` as a **callable provider** `(ReadonlyContext) -> str` reads upstream `ctx.state` inside a workflow node (not just top-level agents). ADK uses the provider's returned string verbatim — it does **not** re-template it, so embedded JSON braces are safe. |
| Structured output | `output_schema=ReviewQueue` + `output_key="review_queue"` lands an **already-parsed dict** in state (ADK parses for us). |
| Persistence boundary | a trailing `FunctionNode` reads that dict from `state["review_queue"]` and drives per-asset Mongo writes — the `LlmAgent` node never touches the DB. |
| Eval mock boundary | `before_model_callback` returning a canned `LlmResponse` short-circuits the live call while `output_schema`/`output_key` still fire — the analogue of Step 4's `_default_vision_fixture_provider`. |

The live run additionally confirmed a real `gemini-2.5-flash` single_turn node honors the schema **and** that the D-026 identity composition emerges from the prompt unprompted ("Prioritize exploitation of assets featuring Lionel Messi given the narrative angle").

Because the spike is clean, we take **Path A** (the spec-literal `LlmAgent` node). The spike is the validation citation for the D-entry (§ Branch housekeeping).

**Why this is conceptually correct, not just spec-compliant:** the output (`ReviewQueue` with per-item rationale + `strategy_summary`) is byte-identical to what a `FunctionNode` would produce; a demo viewer cannot tell the primitives apart. The difference is in the architecture: with an agent node, the graph reads "7 deterministic nodes + 1 agent," and the agentic boundary is a structural fact a judge/maintainer/trace-inspector sees without being told. Steps 2 and 4 already call the LLM via `FunctionNode`, so "uses the LLM" does not distinguish Step 5 — only the agent-node primitive does.

---

## What this capability delivers

The capability is realized as **three workflow nodes**, because an `LlmAgent` node can neither read MongoDB nor perform deterministic joins — those are flanking `FunctionNode` concerns (separation of computation from judgment, per D-019/D-021):

1. **`prepare_queue_candidates` (`FunctionNode`)** — mechanical. Reads `similarity_results` and `scored_assets` from state, joins them by `asset_id`, and splits the event's assets into two candidate pools by a similarity cutoff:
   - **exploitation candidates** — assets whose top-neighbor similarity ≥ `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` (resemble past performers; carry forward `inferred_route` from similarity).
   - **discovery pool** — assets with weak/empty neighbors (no historical analogue; `product_route` unset).
   Writes `queue_candidates = {"exploitation": [...], "discovery": [...]}` to state. Each candidate payload carries `asset_id`, `top_similarity`, `inferred_route`, `scores`, `detected_subjects`.

2. **`propose_review_queue` (`LlmAgent`, `mode='single_turn'`)** — the judgment. An instruction provider builds the prompt from `event_narrative` + `queue_candidates`. The model:
   - **orders the exploitation half** by event-narrative fit, upweighting assets whose `detected_subjects` intersect the narrative's `key_figures` (D-026); applies the technical-fitness quality gate (may demote/drop a matched-but-unfit asset, with rationale, per D-017);
   - **selects the discovery subset** worth surfacing and assigns each a `product_route` (the one place there is no similarity signal to lean on);
   - attaches a one-sentence **rationale** to every surfaced item and writes a `strategy_summary`.
   Emits a `ReviewQueue` via `output_schema`; ADK writes the parsed result to `state["review_queue"]` via `output_key`.

3. **`persist_review_queue` (`FunctionNode`)** — mechanical. Reads `state["review_queue"]` and, for every surfaced item, persists `queue_type`, `product_route`, `queue_rank`, `queue_rationale` onto the asset document. **Routing invariant (D-015):** for exploitation items the persisted `product_route` is the *mechanical* `inferred_route` from `prepare_queue_candidates` (similarity implies the route — the agent orders but does not re-route); for discovery items it is the agent's chosen route. Discovery-pool assets the agent did *not* surface keep `queue_type=None` (the un-surfaced remainder). Writes `review_queue` back into the dispatch result for the coordinator to present.

Consumed by `draft_campaigns_for_queue` (Step 6) — reads the persisted per-asset queue fields (queue_type, product_route, rank, rationale) as copy substrate.

---

## The capability surface (D-019 + D-021)

| Surface | Type | Notes |
| --- | --- | --- |
| `prepare_queue_candidates_node` | `FunctionNode` | New. Edge: `score_assets_with_vision → prepare_queue_candidates`. Reads `similarity_results`, `scored_assets`; writes `queue_candidates`. |
| `propose_review_queue_node` | **`LlmAgent(mode='single_turn')`** | New — the first agent node in the graph. Edge: `prepare_queue_candidates → propose_review_queue`. Instruction = callable provider over state; `output_schema=ReviewQueue`, `output_key="review_queue"`. |
| `persist_review_queue_node` | `FunctionNode` | New. Edge: `propose_review_queue → persist_review_queue → END`. Reads `review_queue`; writes per-asset queue fields. |
| `_node_prepare_queue_candidates`, `_node_persist_review_queue` | adapters (`src/capabilities/__init__.py`) | Same `parameter_binding="state"` pattern as the existing four adapters. The `LlmAgent` node needs no adapter — it reads/writes state via the provider + `output_key`. |

Internal Python pieces added this step (none agent-facing; the agent-facing surface is the workflow, dispatched by the unchanged `run_event_pipeline` shim):

| Piece | File | Purpose |
| --- | --- | --- |
| `split_candidates_by_cutoff(similarity_results, scored_assets, cutoff)` | `src/capabilities/queue.py` | **Pure function** — join + cutoff split. Unit-tested in isolation (deterministic). |
| `queue_instruction_provider(ctx)` | `src/capabilities/queue.py` | Reads state, loads `propose_review_queue` prompt, formats it with narrative + candidate JSON. Returns the full prompt string. |
| `build_review_queue_node()` | `src/capabilities/queue.py` | Constructs the `LlmAgent` node (model = `GEMINI_QUEUE_MODEL`, provider instruction, `output_schema`/`output_key`, eval-seam `before_model_callback`, and `generate_content_config` with an explicit `max_output_tokens` — the spend bound for the per-item-reasoning output, per `safety-measures.md` Gap 2). |
| `_queue_model_callback(cc, req)` + `_FIXTURE_RESPONSE` | `src/capabilities/queue.py` | Eval seam. Always attached; returns `None` (proceed to live model) unless `_FIXTURE_RESPONSE` is set, in which case it returns a canned `LlmResponse`. Import-order-safe (checked at call time, not build time). |
| `persist_review_queue(ctx)` | `src/capabilities/queue.py` | Reads `review_queue`, calls `save_queue_assignment` per surfaced item. |
| `save_queue_assignment(asset_id, queue_type, product_route, rank, rationale)` | `src/db/assets.py` (extension) | One `update-many` setting the four per-asset queue fields. Does **not** change `status` (no "queued" status exists; assets stay `"scored"` until Step 6 sets `"campaign_draft_created"`). |

`get_assets_for_event`, `get_event` reused unchanged. Per D-019, `MongoMCPClient` stays the only programmatic client.

---

## What the LLM does in this capability

Three LLM invocations across a Step 5 dispatch:

1. **Coordinator dispatch decision** (outside the workflow) — unchanged from Steps 1–4.
2. **The strategic queue-assembly call** (the `LlmAgent` node, once per dispatch) — **this is the strategic decision**, the only judgment-shaped LLM call in the system (per `agentic-model.md`). Single turn, no tool loop, `output_schema=ReviewQueue`.
3. *(none other)* — `prepare`/`persist` are deterministic.

The strategic call is judgment under bounded ambiguity (type-2 agentic value, per the reframe): the action space is bounded (known assets, two queues, known routes), but the right *composition* for this event is not. The exploitation/discovery membership is mechanically pre-determined (cutoff); the agent's value is **ordering** exploitation, **selecting** discovery, applying the **quality gate**, composing **identity** signal against the narrative, and producing legible **rationale**.

### Why `GEMINI_QUEUE_MODEL` defaults to `flash`, not the spec's `flash-lite`

`02-architecture.md` line 386 currently folds the strategic node under `GEMINI_MODEL` (`flash-lite`). This is the single most judgment-dense node in the system; flash-lite is documented as unreliable at judgment-dense decision points (CLAUDE.md, the coordinator delegate/dispatch note) and D-028 already set the precedent of a dedicated env var defaulting to `flash` for the judgment-laden Vision call. By the same reasoning, `propose_review_queue` warrants `flash`. A new `GEMINI_QUEUE_MODEL` env var (default `gemini-2.5-flash`) parallels `GEMINI_VISION_MODEL`; the spike's live run used flash and honored the schema cleanly. This overrides the spec's flash-lite default — recorded in the D-entry + spec amendment (§ Branch housekeeping).

---

## What the capability does internally

```text
prepare_queue_candidates (FunctionNode)
    similarity_results = ctx.state["similarity_results"]   # [{asset_id, neighbors, inferred_route}]
    scored_assets      = ctx.state["scored_assets"]        # [{asset_id, scores, detected_subjects}]
    exploitation, discovery = split_candidates_by_cutoff(similarity_results, scored_assets, cutoff)
        # per asset: top_similarity = max(n.similarity for n in neighbors) or 0.0 if empty
        # top_similarity >= cutoff → exploitation (carry inferred_route); else → discovery (route None)
    ctx.state["queue_candidates"] = {"exploitation": exploitation, "discovery": discovery}

propose_review_queue (LlmAgent, single_turn)
    instruction = queue_instruction_provider(ctx)          # narrative + queue_candidates → prompt
    → model emits ReviewQueue (output_schema)
    → ctx.state["review_queue"] = <parsed dict>             # via output_key

persist_review_queue (FunctionNode)
    queue = ReviewQueue.model_validate(ctx.state["review_queue"])
    routes = {c["asset_id"]: c["inferred_route"]                 # from queue_candidates in state
              for c in ctx.state["queue_candidates"]["exploitation"]}
    violations = []
    for item in queue.exploitation:
        if item.asset_id not in routes:                          # defensive — LLM cross-assigned/invented
            violations.append(("exploitation", item.asset_id)); continue
        save_queue_assignment(item.asset_id, "exploitation", routes[item.asset_id], item.rank, item.rationale)
    discovery_ids = {c["asset_id"] for c in ctx.state["queue_candidates"]["discovery"]}
    for item in queue.discovery:
        if item.asset_id not in discovery_ids:
            violations.append(("discovery", item.asset_id)); continue
        save_queue_assignment(item.asset_id, "discovery", item.product_route, item.rank, item.rationale)
    return {"review_queue": queue.model_dump(mode="json"), "membership_violations": violations}
```

`persist_review_queue` reads **both** `review_queue` (the LLM output) and `queue_candidates` (for the mechanical exploitation routes) from state. It is **defensive by design**: if the LLM cross-assigns a discovery asset into exploitation or invents an `asset_id`, persist skips that item and records it in `membership_violations` rather than `KeyError`-ing — so the strategy-coherence membership assertion (b) fails *legibly* in the eval instead of surfacing as a stack trace.

**Preconditions.** Per the reframe (§ Enforced vs. emergent), the capability hard-refuses if any of event / assets / similarity results / scores / narrative are missing — with a self-correcting `PreconditionError`. **All precondition checks live in `prepare_queue_candidates`** (a normal `FunctionNode`, where raising behaves like every other capability), **not in the instruction provider** — ADK's error semantics for a raising instruction provider are untested by the spike, so we route around that path entirely. `prepare_queue_candidates` reads `similarity_results` and `scored_assets` from state and also checks `event_narrative` presence (the provider then assumes a validated state). Under the D-024 graph order all are always present at this node, so the check is defense-in-depth for direct calls (unit tests). Example message:

```text
Cannot propose review queue for evt-...:
  - similarity_results not found (call find_similar_assets first)
  - scores not found (call score_assets_with_vision first)
```

**Empty pools are valid, not failures.** An event whose assets all matched strongly → empty discovery pool (agent surfaces exploitation only). An event with no strong matches (the demo's group-stage draw) → thin/empty exploitation, discovery-heavy. The capability does not treat either as an error; this is exactly the cross-event strategic contrast the demo turns on.

---

## Pydantic models (new)

```python
# LLM output schema — extra="forbid" omitted: Gemini's response_schema rejects
# additionalProperties:false (established in Steps 2/4).
class QueueItem(BaseModel):
    asset_id: str
    queue_type: Literal["exploitation", "discovery"]
    rank: int                                   # 1-based within its half
    product_route: Literal["poster", "tshirt", "social_only"] | None
    rationale: str                              # one-sentence operator-facing reasoning


class ReviewQueue(BaseModel):
    event_id: str
    exploitation: list[QueueItem]
    discovery: list[QueueItem]
    strategy_summary: str                       # overall reasoning; demo-legible
```

**Naming:** the persisted enum value is `"discovery"`, matching the existing `Asset.queue_type` field (`"exploitation" | "discovery" | null`) and the `assets` schema in `02-architecture.md`. The reframe prose calls this half "exploration"; they are synonyms. **Use `"discovery"` in code** to match the model already on disk — noted here so Step 6 does not trip on it.

Modification to existing `Asset` (parallels how Step 4 added `detected_subjects`):

```python
class Asset(BaseModel):
    # ... existing fields (queue_type, product_route already present) ...
    queue_rank: int | None = None          # new — set by propose_review_queue
    queue_rationale: str | None = None     # new — per-item operator-facing reasoning
```

`queue_type` and `product_route` already exist on `Asset` (CLAUDE.md: "Step 4 does **not** write `product_route` or `queue_type` — Step 5's boundary"). Step 5 is the first writer of all four queue fields.

**Why persist `rank` + `rationale` (a schema extension beyond the spec's `product_route + queue_type` writes).** D-022 set the project's persistence philosophy: persist composed artifacts onto their document rather than thread them through session state. Step 6 (`draft_campaigns_for_queue`) needs the rationale as copy substrate and the rank as ordering; persisting them makes the queue resumable across ADK sessions (the `assets` collection is the durable state layer per `02-architecture.md`) and demo-legible (the queue can be re-rendered from Mongo, not only from a live run). Recorded in the D-entry + `assets` schema amendment.

---

## Components

| # | Component | File | Purpose |
| --- | --- | --- | --- |
| 1 | `QueueItem`, `ReviewQueue` models | `src/models.py` (extension) | LLM output schema |
| 2 | `Asset.queue_rank`, `Asset.queue_rationale` | `src/models.py` (modification) | New persisted per-asset queue fields |
| 3 | `save_queue_assignment` wrapper | `src/db/assets.py` (extension) | One `update-many` setting queue_type, product_route, queue_rank, queue_rationale |
| 4 | `split_candidates_by_cutoff` | `src/capabilities/queue.py` | Pure join + cutoff split → (exploitation, discovery) |
| 5 | `queue_instruction_provider` | `src/capabilities/queue.py` | Builds the strategic prompt from state |
| 6 | `_queue_model_callback` + `_FIXTURE_RESPONSE` | `src/capabilities/queue.py` | Eval mock seam (canned `LlmResponse`) |
| 7 | `build_review_queue_node` | `src/capabilities/queue.py` (replaces stub) | Constructs the `LlmAgent` strategic node |
| 8 | `persist_review_queue` | `src/capabilities/queue.py` | Reads `review_queue`, persists per-asset assignments |
| 9 | adapters + nodes + graph edges | `src/capabilities/__init__.py` (modification) | `_node_prepare_queue_candidates`, `prepare_queue_candidates_node`, `propose_review_queue_node` (from `build_review_queue_node()`), `_node_persist_review_queue`, `persist_review_queue_node`; extend chain tuple to 8 elements |
| 10 | `run_event_pipeline` return | `src/agent.py` (modification) | Add `review_queue` to the returned state dict |
| 11 | Strategist prompt | `prompts/v3/propose_review_queue.md` (new) | The judgment prompt — exploitation ordering, discovery selection, identity composition, quality gate, rationale, "surface meaningful work" nudge |
| 12 | Coordinator prompt | `prompts/v3/coordinator_system.md` (light edit) | One-line addition: after the pipeline returns, present the proposed queue (both halves) with per-item reasoning to the operator |
| 13 | Conftest helpers | `tests/conftest.py` (extension) | `build_valid_queue_item()`, `build_valid_review_queue()` |
| 14 | Tests — unit | `tests/test_step_5.py` (new), `tests/test_models.py` (extension) | Models; `split_candidates_by_cutoff` (cutoff boundary, empty neighbors → discovery, join correctness); `save_queue_assignment` envelope; `persist_review_queue` (exploitation route = mechanical, discovery route = LLM, un-surfaced assets untouched, cross-assigned/invented asset_id recorded as a violation not a crash); provider prompt structure; `prepare_queue_candidates` raises `PreconditionError` on missing similarity/scores/narrative |
| 15 | Tests — Tier 1 plumbing eval | `tests/evals/test_step_5_trace.py` (new) | Deterministic, mocked via `_FIXTURE_RESPONSE` — split/parse/persist/routing/violation-legibility. Zero live calls; CI ship gate (see § Evaluation) |
| 16 | Tests — Tier 2 coherence eval | `tests/evals/test_step_5_coherence.py` (new) | Live strategic node, upstream seeded — strategy-coherence assertions; D-020 95%/20-run; run deliberately, not on offline CI |
| 17 | Eval conftest extension | `tests/evals/conftest.py` (modification) | Seed similarity + scores + narrative fixtures into pipeline state; expose `_FIXTURE_RESPONSE` control (Tier 1); transient-API-error retry/exclude helper (Tier 2) |

---

## Dependency order

1. **Models** — `QueueItem`, `ReviewQueue`; add `Asset.queue_rank`, `Asset.queue_rationale`
2. **Conftest helpers** — `build_valid_queue_item()`, `build_valid_review_queue()`
3. **`save_queue_assignment` wrapper** — unit-tested via mocked client (asserts `update-many` `$set` shape, no status change)
4. **`split_candidates_by_cutoff`** — pure-function unit tests (cutoff boundary inclusive/exclusive, empty-neighbors → discovery, join by asset_id, inferred_route carried)
5. **Strategist prompt** — `prompts/v3/propose_review_queue.md`
6. **`queue_instruction_provider`** — unit-tested with a fake `ReadonlyContext` (asserts narrative + both pools appear in the built prompt; assumes validated state — does **not** raise, preconditions are `prepare`'s job)
7. **`build_review_queue_node` + `_queue_model_callback`** — node constructs; callback returns `None` when `_FIXTURE_RESPONSE` unset, canned `LlmResponse` when set
8. **`persist_review_queue`** — unit test with mocked `save_queue_assignment` + seeded `review_queue` + `queue_candidates` (exploitation route mechanical, discovery route from LLM, un-surfaced discovery untouched)
9. **Adapters + nodes + graph edges** (`src/capabilities/__init__.py`) — extend chain tuple to `(START, ingest, context, similarity, scoring, prepare_queue, propose_review_queue, persist_queue)`
10. **`run_event_pipeline`** returns `review_queue`; verify `build_coordinator()/build_workflow()` import OK
11. **Eval scaffolding** (`tests/evals/conftest.py`) — upstream-seeding fixtures + `_FIXTURE_RESPONSE` control + transient-API-error retry/exclude helper
12. **Tier 1 plumbing eval** (`tests/evals/test_step_5_trace.py`) — deterministic/mocked, single run, CI gate
13. **Tier 2 coherence eval** (`tests/evals/test_step_5_coherence.py`) — live, `EVAL_REPEAT=20`, ≥ 95%, run deliberately

---

## Strategist prompt template (load-bearing — eval asserts on its output)

`prompts/v3/propose_review_queue.md` — formatted by `queue_instruction_provider` (Python `.format`, not Jinja; the provider's output is used verbatim by ADK). Shape:

```text
You are the strategist assembling the operator review queue for one sports event.
Your output is the single judgment in an otherwise automated pipeline: a ranked,
reasoned queue the operator will review. Output JSON matching the ReviewQueue schema.

EVENT
- event_id: {event_id}
- narrative angle: {narrative_angle}
- key figures: {key_figures}

You are given two candidate pools, already split by similarity to past performers.

EXPLOITATION CANDIDATES (resembled past winners; routing is already implied by similarity):
{exploitation_json}

DISCOVERY POOL (did NOT resemble past winners; no routing signal):
{discovery_json}

ASSEMBLE THE QUEUE
- Exploitation half: ORDER these by fit with the event narrative. Upweight any asset
  whose detected_subjects include a key figure — identity match beats generic scene.
  Apply the quality gate: an asset with low quality_score / merch_score is technically
  unfit for production; demote it or drop it, and say so in its rationale. Carry each
  item's product_route forward unchanged (similarity already decided it).
- Discovery half: SELECT which assets are worth the operator's time despite not matching
  past winners. This is your hardest call — there is no similarity signal, just the image's
  scores and what the narrative makes salient. Surface the ones with something worth saying;
  choose a product_route for each (poster, tshirt, or social_only). Surface meaningful work —
  do not return an empty discovery half when a candidate clearly merits attention.
- Every surfaced item gets a 1-based rank within its half and a ONE-SENTENCE rationale the
  operator can read. Exploitation rationales speak to narrative fit; discovery rationales
  answer "why is this worth your time despite the miss?"
- Write a short strategy_summary describing the shape of this queue and why it fits THIS event.
```

The "upweight identity match" line is the D-026 composition. The "surface meaningful work" nudge is the demo-coherence mitigation against under-surfacing (reframe § Demo coherence threat table). The "quality gate" line is D-017's technical-fitness role.

---

## System prompt context

`prompts/v3/coordinator_system.md` gets a **one-line addition**: after `run_event_pipeline` returns, present the proposed review queue — both halves, with each item's rank, route, and rationale — to the operator for review. (Full HITL approve/reject/edit is Step 7; Step 5 only produces and surfaces the queue.) No other coordinator change; the workflow extends transparently beneath the dispatch tool, as in Steps 3–4.

---

## Evaluation — two-tier (code correctness isolated from AI infra flakiness)

Step 4 mocked its LLM call in the gate because Vision had per-asset cardinality (~400 calls/gate) and Vision quality was not the strategic claim. Step 5 is the first capability whose *judgment* is the claim, so the eval has to exercise the real model somewhere — but **the CI/code-correctness signal must not depend on the model being reachable** (a 503, a rate-limit, or a model-availability blip is not a code regression). Resolution: **two tiers, in two files.**

**Tier 1 — plumbing gate (deterministic, mocked, CI ship gate).** `tests/evals/test_step_5_trace.py`. Uses the `_FIXTURE_RESPONSE` canned `LlmResponse` seam (spike-validated) — **zero live model calls.** Runs offline, in CI, with no `GOOGLE_API_KEY`. Because it is deterministic, a **single run** is authoritative (no 20× repetition — repetition exists to catch LLM nondeterminism, of which there is none here). Asserts the code path:

- (T1-a) `ReviewQueue` parses from `output_key` state (the canned dict round-trips through ADK).
- (T1-b) `prepare_queue_candidates` split is correct against the cutoff (exploitation vs. discovery membership), join by `asset_id`, `inferred_route` carried.
- (T1-c) `persist_review_queue` wrote a `save_queue_assignment` per surfaced item; exploitation route = mechanical `inferred_route` (D-015 invariant); discovery route = LLM value; un-surfaced discovery assets untouched.
- (T1-d) membership-violation legibility: a deliberately cross-assigned canned fixture is recorded in `membership_violations`, not crashed on.
- (T1-e) coordinator dispatched `run_event_pipeline` exactly once; reasoning text present pre-dispatch (CoT directive); on failure `dump_trace()`.

This is the gate `main` stays green against. It cannot flake on AI infra.

**Tier 2 — strategy-coherence eval (live, run deliberately, the D-020 pass-rate gate).** `tests/evals/test_step_5_coherence.py`. Seeds deterministic `event_narrative` + `similarity_results` (mix of strong-match and no-match) + `scored_assets` (one identity-matched, high-emotion discovery candidate), then runs `prepare → propose_review_queue (LIVE) → persist`. This is where the **95% / 20-run** discipline (D-020) lives, because this is where nondeterminism lives. Run pre-merge / locally / nightly — **not** a blocker on the offline code-CI signal. Assertions (failure category 6, D-021 — the load-bearing new class), written tolerant to LLM variability:

- (T2-a) every exploitation item's `asset_id` ∈ exploitation candidate set; every discovery item's ∈ discovery pool (no invent/cross-assign).
- (T2-b) exploitation non-empty (matched winners surfaced).
- (T2-c) discovery non-empty (the worth-it candidate surfaced) — the "surface meaningful work" property.
- (T2-d) identity-matched asset appears in exploitation, not dropped (D-026); soft "ranked 1 or 2" included but tuning-flagged.
- (T2-e) every surfaced item has non-empty `rationale`; `strategy_summary` non-empty (demo-legibility).
- (T2-f) `queue_type` matches half; ranks positive and distinct within each half.

**Infra-vs-judgment separation inside Tier 2.** A transient API error (5xx / rate-limit / timeout) is **not** counted as a judgment failure — the harness retries it or excludes it from the pass-rate denominator, so the 95% measures the model's *judgment*, not the API's *uptime*. (This is the same concern that motivates two tiers, applied within Tier 2.)

**Empirical validation — the eval risk is measured, not assumed.** `spike/adk_llm_node_queue_spike.py passrate 20` already ran the live strategic node 20× against the seeded fixture and the Tier-2 assertions: **20/20 (100%)**, including the two flake-risk assertions (discovery-nonempty, soft identity-top-2). Every run produced `exploitation=[a1,a2], discovery=[a3]`. The **lever** is an *unambiguous* fixture (worth-it discovery candidate = very high `emotional_score` + identity match; un-worth-it = genuinely weak). Tier 2 should be expected to pass comfortably; if it ever softens, the remediation ladder is prompt-first per `evaluation-strategy.md` — never a heuristic shortcut (Hard Constraint #1).

---

## Verification checkpoints

| After | Command | Must pass |
| --- | --- | --- |
| Models | `.venv/bin/python -m pytest tests/test_models.py -v` | `QueueItem`/`ReviewQueue` validate; reject bad `queue_type`; `Asset.queue_rank`/`queue_rationale` accept int/str and None; existing model tests pass. |
| Wrapper (unit) | `.venv/bin/python -m pytest tests/test_step_5.py -v -k wrapper` | `save_queue_assignment` → mocked client `update-many`, filter on `asset_id`, `$set` = {queue_type, product_route, queue_rank, queue_rationale}, no `status` key. |
| Split (unit) | `.venv/bin/python -m pytest tests/test_step_5.py -v -k split` | `split_candidates_by_cutoff`: cutoff boundary, empty neighbors → discovery, join by asset_id, inferred_route carried into exploitation candidates. |
| Prepare + provider + persist (unit) | `.venv/bin/python -m pytest tests/test_step_5.py -v -k "prepare or provider or persist"` | `prepare_queue_candidates` raises `PreconditionError` on missing narrative/similarity/scores; provider embeds narrative + both pools (no raise); `persist_review_queue` uses mechanical route for exploitation, LLM route for discovery, leaves un-surfaced assets untouched, records cross-assigned/invented asset_ids as violations (no crash). |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–5 unit tests green. |
| Import check | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Graph builds with the three new nodes. |
| **Tier 1 — plumbing gate (deterministic, mocked, CI)** | `.venv/bin/python -m pytest tests/evals/test_step_5_trace.py -v` | Assertions (T1-a)–(T1-e). Zero live calls; single run authoritative. This is the gate `main` stays green against. |
| **Tier 2 — strategy-coherence (live, deliberate)** | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_5_coherence.py -v` | ≥ 19/20 (95%, D-020) on assertions (T2-a)–(T2-f); transient API errors retried/excluded, not counted as judgment failures. Run pre-merge/local/nightly — not on offline code-CI. |

Step 5 is the first capability to exercise **failure category 6 (strategy coherence)** per `docs/evaluation-strategy.md`, alongside categories 1 (tool selection — dispatch), 4 (tool-output handling — the agent reasons over scores/similarity it's given), and 5 (end-state — queue persisted).

---

## Risks

| Risk | Mitigation |
| --- | --- |
| **Tier 2 live eval flakes** (LLM variability, or AI infra — 503 / rate-limit) | **Code CI never depends on it** — Tier 1 (deterministic, mocked) is the gate `main` stays green against. Tier 2 measured **20/20** on the spike probe; assertions tolerant (subset/non-empty/presence). Transient API errors are retried/excluded from the pass-rate denominator (infra ≠ judgment). |
| **Under-surfacing** — agent returns empty discovery when a candidate merits it (T2-c fails) | **Measured 20/20** with the unambiguous fixture. Prompt "surface meaningful work" nudge. If it ever softens, climb the ladder prompt-first (strengthen nudge → few-shot example → as a last resort, a minimum-discovery floor in `prepare`). Do **not** jump to a heuristic — that would collapse the one strategic decision (Hard Constraint #1). The fixture's discovery candidate must stay unambiguous (high emotional + identity). |
| **Identity composition not honored** — Messi asset buried/dropped (T2-d) | **Measured 20/20** (including the soft top-2 rank). Prompt names the upweight rule explicitly; spike's live run honored it spontaneously. Remediation: prompt → docstring → (last) a mechanical identity-boost in `prepare` exposed to the LLM as a hint. |
| **Agent re-routes exploitation** despite similarity having decided it | `persist_review_queue` ignores the LLM's `product_route` for exploitation items and uses the mechanical `inferred_route` (D-015 invariant enforced in code, not trusted to the prompt). LLM route is honored only for discovery. |
| **Cutoff is a magic number that shapes the demo queue** | `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` is env-configurable (default `0.75`). It is **tuned against the demo corpus**, not a fixed truth — stated in the env table and the D-entry. Atlas cosine `vectorSearchScore` is normalized to [0,1]. |
| **"90% / 10%" in `01-requirements.md` read as an enforced ratio** | The split is **emergent** from the cutoff + the agent's discovery selection — there is no enforced budget or cap (faithful to the reframe: the agent decides what merits surfacing). The 90/10 is the *expected emergent shape* for a typical event, not a constraint. One sentence in the requirements housekeeping edit (§ Branch housekeeping item 4) prevents Step 6 / a reviewer from expecting a hard ratio. |
| **ADK re-templates the provider string and chokes on JSON braces** | Validated false by the spike — a callable instruction provider's output is used verbatim. Documented so it isn't "fixed" later. |
| **`output_key` lands a raw JSON string, not a dict** | Spike confirmed ADK lands a parsed **dict**. `persist`/eval use `ReviewQueue.model_validate(...)` and tolerate both via an isinstance check (matches the spike's persist node). |
| **PreconditionError raised mid-graph aborts the run ungracefully in the demo** | Under D-024 graph order all preconditions are satisfied at this node; the check only fires on direct/unit calls. Demo path never hits it. |
| **Discovery `product_route` from the LLM is an invalid value** | `QueueItem.product_route` is a `Literal` over the three routes (or null); `output_schema` constrains the model; `model_validate` rejects anything else before persist. |

**Strategy coherence is the primary risk surface in Step 5** — it is the one place the system has no deterministic ground truth. The live eval is the regression net; the remediation ladder (never a heuristic shortcut) is the response to a soft result.

---

## Env vars required

| Var | Purpose | Default |
| --- | --- | --- |
| `GEMINI_QUEUE_MODEL` | **New** — model for the strategic queue node | `gemini-2.5-flash` |
| `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF` | **New** — top-neighbor similarity at/above which an asset is an exploitation candidate | `0.75` (corpus-tuned) |
| `GOOGLE_API_KEY` | Existing — `google.genai` / ADK model auth | required |
| `GEMINI_VISION_MODEL` | Existing — Step 4 | `gemini-2.5-flash` |
| `GEMINI_MODEL` | Existing — other workflow nodes | `gemini-2.5-flash-lite` |
| `GEMINI_COORDINATOR_MODEL` | Existing — coordinator | `gemini-2.5-flash` |

Both new vars documented in the README env section.

---

## Output consumed by

- **`draft_campaigns_for_queue` (Step 6)** — reads the persisted per-asset queue fields (`queue_type`, `product_route`, `queue_rank`, `queue_rationale`) as copy substrate; the rationale grounds the per-item draft.
- **The coordinator** — surfaces the queue (both halves, per-item reasoning) to the operator after dispatch.
- **The trace/demo** — the strategic-agent moment: per-item reasoning on screen (reframe § Demo coherence, ~1:00–1:30 of Event 1, ~2:00–2:20 of Event 2). The cross-event contrast (rich exploitation vs. discovery-heavy) is the load-bearing evidence that the agent reasons strategically rather than running a fixed pipeline.

---

## What changed from prior planning docs

- **First in-graph `LlmAgent` node** — every prior capability is a `FunctionNode`. Step 5 introduces the agent node (Path A), validated by `spike/adk_llm_node_queue_spike.py`. Confirms `02-architecture.md`'s spec intent.
- **Three nodes for one capability** — `prepare` (mechanical split) + `propose_review_queue` (judgment) + `persist` (Mongo write). The agent node cannot do I/O or joins; flanking `FunctionNode`s handle them (D-019 separation).
- **`GEMINI_QUEUE_MODEL` defaults to `flash`** — overrides the spec's flash-lite for the strategic node (D-028 precedent; judgment density).
- **`Asset.queue_rank` + `queue_rationale` persisted** — schema extension beyond the spec's `product_route + queue_type` writes (D-022 persistence philosophy; Step 6 substrate).
- **Two-tier eval** — Tier 1 (deterministic, mocked) is the CI ship gate so code correctness is isolated from AI infra flakiness (503/rate-limit); Tier 2 (live, deliberate) is where the D-020 95%/20-run judgment gate lives. Opposite emphasis from Step 4's single mocked gate, because here the judgment *is* the claim — but the code signal stays mock-clean.

---

## Branch housekeeping (lands in the first commits on this branch, before implementation)

Doc-only; implementation must not contradict the spec it is written against. Per CLAUDE.md, every `docs/specs/` change needs a `tracking.md` D-entry.

1. **New D-entry (D-029): `propose_review_queue` as in-graph `LlmAgent` node + queue-assembly mechanics** (`tracking.md`). Captures: (a) Path A confirmed — first in-graph `LlmAgent(mode='single_turn')` node, validated by `spike/adk_llm_node_queue_spike.py` (cite the four claims); (b) `GEMINI_QUEUE_MODEL` defaults to `flash`, overriding the spec/D-024 flash-lite default for this node (D-028 reasoning); (c) mechanical similarity-cutoff pre-split (env `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF`, corpus-tuned) feeding LLM ordering (exploitation) + selection (discovery); (d) exploitation routing stays mechanical (`inferred_route`, D-015), LLM routes only discovery; (e) persist `queue_rank` + `queue_rationale` onto `assets` (D-022 philosophy); (f) `"discovery"` is the persisted enum (synonym of the reframe's "exploration"). Refines D-021, D-024, D-026; updates the model-default surface from D-028's pattern.

2. **`docs/specs/02-architecture.md`** — strategic node model → `GEMINI_QUEUE_MODEL` (`flash`), not flash-lite (lines 353, 386); `assets` schema gains `queue_rank`, `queue_rationale`; the `propose_review_queue` MCP call list shows the actual writes (queue_type, product_route, queue_rank, queue_rationale — no status change) and notes the `prepare`/`persist` flanking nodes around the `LlmAgent` node; graph diagram reflects the three nodes.

3. **`docs/db-wrapper-inventory.md`** — add `save_queue_assignment(asset_id, queue_type, product_route, rank, rationale) -> None`.

4. **`docs/specs/01-requirements.md` § `propose_review_queue`** — one sentence confirming rank + rationale are persisted per asset (not only returned in state).

5. **`docs/safety-measures.md`** — confirm the strategic node carries `max_output_tokens` per the spend bound (the queue payload is bounded by asset count; note it).

Sequence on this branch: (1) housekeeping commit (items 1–5, doc-only) → (2) plan + tasks gates → (3) implementation per task order → (4) trace eval + pass-rate gate → (5) merge to `main` with the updated "Next action" in `CLAUDE.md`.
