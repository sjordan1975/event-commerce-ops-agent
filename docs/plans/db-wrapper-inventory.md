# DB Wrapper Inventory

> **Reframed for D-021** (2026-05-26). Pre-D-021 this doc framed wrappers as the agent's `FunctionTool` surface. Post-D-021, wrappers are **internal Python functions** that capabilities call; the agent's surface is the 9 capabilities listed in `docs/plans/strategic-agent-reframe.md` § The capability surface. Substantive content (MCP discovery, `MongoMCPClient` design, the 23-ish domain operations) is largely unchanged — only the framing and three names. Naming changes: `find_similar_assets` (wrapper) → `vector_search_assets` (capability keeps the old name); `score_asset_with_vision` (wrapper) inlined into the `score_assets_with_vision` capability; `await_human_approval` retired (the `request_human_approval` capability *is* the `LongRunningFunctionTool`).

Draft — output of project phase 1 (discovery), input to phase 2 (build).

This document lists the full set of domain-named Python wrappers that capabilities call internally across the 9-capability surface. Each wrapper calls MongoDB MCP internally via the `MongoMCPClient` programmatic client. The agent itself does not call wrappers directly; the agent calls capabilities, capabilities call wrappers. See D-019 (wrapper-vs-raw-MCP discipline) and D-021 (capability surface) in `tracking.md` for rationale.

---

## Project phases

| Phase | When | Concern |
|---|---|---|
| 1. Discovery | Engineering, out-of-band | What MongoDB MCP tools exist; which we use internally |
| 2. Build | Engineering | Implement internal wrappers in `src/db/`; cover the operations all 9 capabilities need |
| 3. Runtime | Demo day | Agent calls capabilities (`src/capabilities/`); capabilities call internal wrappers; wrappers call MCP. The agent never sees the wrapper layer. |

The naive failure mode is collapsing phase 1 into phase 3 — letting the agent "discover" MCP capabilities at runtime. That is the trap D-019 rejects.

---

## Module structure

```text
src/db/                ← internal wrappers (NOT agent-facing)
  __init__.py          ← lazy get_client(); internal wrapper exports
  client.py            ← single MongoMCPClient + connection lifecycle
  events.py            ← internal wrappers over events collection
  assets.py            ← internal wrappers over assets collection
  campaigns.py         ← internal wrappers over campaigns collection
  approvals.py         ← internal wrappers over approvals collection
  performance.py       ← internal wrappers over performance collection
  player_context.py    ← internal wrappers over player_context collection

src/capabilities/      ← agent-facing tools (the 9-capability surface)
  __init__.py          ← all_function_tools = [FunctionTool(...) per capability]
  ingest.py            ← ingest_event_batch
  context.py           ← build_event_context (Step 2)
  similarity.py        ← find_similar_assets (Step 3 — capability)
  scoring.py           ← score_assets_with_vision (Step 4)
  queue.py             ← propose_review_queue (Step 4-ish — the strategic decision)
  drafting.py          ← draft_campaigns_for_queue (Step 5)
  approval.py          ← request_human_approval (Step 6 — LongRunningFunctionTool)
  execution.py         ← execute_approved_campaigns (Step 7)
  outcomes.py          ← record_outcomes (Step 8)
```

Internal wrappers grouped by collection (not by capability) so ownership and schema authority is clear. Capabilities grouped by file per agent-facing operation. Wrappers used by multiple capabilities live with their collection. Wrappers return Pydantic models or plain dicts; never raw MongoDB documents with `_id` bleeding through.

### Client design (verified by `spike/adk_mcp_programmatic.py`, 2026-05-25)

The agent's tool list contains **only** the 9 capabilities registered as `FunctionTool`s. `McpToolset` is *not* registered in `agent.tools`, and internal wrappers are *not* registered either. `src/db/client.py` owns a single `McpToolset` instance as a programmatic client; internal wrappers call MCP tools through it; capabilities call the wrappers. This enforces D-019 + D-021 by construction — the agent cannot bypass either layer because neither raw MCP nor the wrappers are in its surface.

Verified pattern:

```python
# src/db/client.py
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters


class MongoMCPClient:
    """Programmatic MongoDB MCP client. Single instance, shared by all wrappers."""

    def __init__(self) -> None:
        self._toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=["-y", "mongodb-mcp-server@latest"],
                    env={...},
                )
            )
        )
        self._tools_by_name: dict[str, object] | None = None

    async def _ensure_tools(self) -> None:
        if self._tools_by_name is None:
            tools = await self._toolset.get_tools()
            self._tools_by_name = {t.name: t for t in tools}

    async def call(self, tool_name: str, args: dict) -> dict:
        await self._ensure_tools()
        tool = self._tools_by_name[tool_name]
        return await tool.run_async(args=args, tool_context=None)

    async def close(self) -> None:
        await self._toolset.close()
```

Domain wrappers use it directly:

```python
# src/db/events.py
async def record_event(event: Event) -> str:
    response = await client.call("insert-many", {
        "database": "event_commerce",
        "collection": "events",
        "documents": [event.model_dump(mode="json")],
    })
    return event.event_id
```

### What the spike confirmed

1. `McpToolset.get_tools()` returns a list of `MCPTool` objects (43 tools from the MongoDB MCP server) — enumeration works without registering the toolset on an agent.
2. Each `MCPTool` has `run_async(args=..., tool_context=...)` returning a structured dict response — programmatic invocation works.
3. The response format is `{"content": [{"type": "text", "text": "..."}, ...]}` (standard MCP content envelope) — wrappers need to extract the meaningful payload from this envelope before returning to callers.
4. `tool_context=None` is required (positional/kwarg) — the API accepts it; passing it as `None` works for non-LLM-driven calls.
5. Use `StdioConnectionParams(server_params=StdioServerParameters(...))`, not bare `StdioServerParameters` — the bare form prints a deprecation warning.
6. The MongoDB MCP server returns responses wrapped with `<untrusted-user-data-...>` boundary tags as a safety annotation. This is for an LLM consumer; the programmatic wrapper just parses past it.

---

## Splitting principle

A wrapper exists for each operation that satisfies all of:

1. **Coherent on its own** — has a clear input/output contract; could meaningfully be called outside the step that introduced it
2. **Atomic from the agent's mental model** — the agent isn't making sub-decisions inside it
3. **Inseparable writes get bundled** — multi-collection writes that always go together and have no independent meaning become one wrapper (e.g. "submit a campaign" inserts into `campaigns`, updates `assets`, inserts into `approvals` — these have no independent meaning)

This produces splits like `record_event` + `record_assets` (independent meaning — you might backfill assets later), and bundles like `submit_campaign_for_review` (campaign without approval queue entry is meaningless).

---

## Internal wrappers used by each capability

### `ingest_event_batch` (was: Step 1 — Ingestion)

The operator hands the capability two distinct things: event metadata (what happened) and an image batch (the media). Internally, the capability validates the metadata, computes timeliness, and writes both event and assets. The split between `record_event` and `record_assets` reflects different cardinality and the future possibility of backfilling assets for an existing event independently.

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `record_event(event: Event) -> str` | `events insert-many` | Returns `event_id`. Validates via Pydantic; timeliness already on the event doc. |
| `record_assets(event_id: str, assets: list[Asset]) -> list[str]` | `assets insert-many` | Returns asset_ids in input order. Pydantic-validated; status defaults to `"ingested"`. |

Plus non-MongoDB:
- `compute_timeliness(outcome_type: str, kickoff_utc: str) -> dict` — pure math. Internal helper used inside `ingest_event_batch`; not agent-facing. *(Pre-D-021 was a direct FunctionTool; reframed per D-021.)*

See `docs/plans/step-1-event-ingestion.md` for the full plan.

### `build_event_context` (was: Step 2 — Event Context Understanding)

This capability has four distinct reads against different collections answering different questions, plus one write at the end. Each read is independently meaningful and used in different combinations across the lifecycle. Splitting the wrappers keeps the trace legible at the wrapper layer and the capability layer clean — the capability orchestrates the four reads, then produces the narrative via an LLM call, then writes it back.

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `get_event(event_id: str) -> Event` | `events find` (one) | Cross-cutting utility — also used by Step 4, Step 5. Lives in `events.py`. |
| `get_past_events_by_outcome(outcome_type: str, limit: int = 10) -> list[Event]` | `events find` | "What other upset victories have we seen?" Historical reference set. |
| `get_performance_baseline_by_outcome(outcome_type: str) -> PerformanceBaseline` | `performance aggregate` | Aggregated conversion stats across past events of this outcome type. Returns channel-broken-down baseline. |
| `get_player_context_for_teams(home_team: str, away_team: str) -> list[PlayerContext]` | `player_context find` | Plain team-name match (D-016). Returns squad members for both sides; agent picks narratively significant ones. One wrapper, not two, because "context for this match" is the domain operation. |
| `save_event_narrative(event_id: str, narrative: EventNarrative) -> None` | `events update-many` | Writes the typed Step 2 output back onto the event doc. Consumed by Step 5. |

### `find_similar_assets` capability (was: Step 3 — Similarity-Grounded Routing)

The two MongoDB writes here are *not* inseparable. Embedding is permanent work that should be saved as soon as it's computed (so we never recompute it). The similarity list is an analytical derivation that depends on the corpus state and could change. The lifecycle differs.

**Wrapper rename per D-021:** the wrapper that runs the vector search is renamed `vector_search_assets` to avoid collision with the capability name `find_similar_assets`. The capability calls the wrapper internally for each candidate embedding.

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `vector_search_assets(embedding: list[float], top_k: int = 20, channel: str \| None = None) -> list[SimilarAsset]` | `assets aggregate` ($vectorSearch) | The load-bearing MongoDB call. Naming makes the Atlas Vector Search feature explicit at the wrapper layer. Optional `channel` narrows the candidate pool. *(Renamed from `find_similar_assets` per D-021 — the capability keeps that name.)* |
| `save_asset_embedding(asset_id: str, embedding: list[float]) -> None` | `assets update-many` | Permanent — once written, never recomputed. |
| `save_similar_assets(asset_id: str, similar_asset_ids: list[str]) -> None` | `assets update-many` | Analytical result; could be recomputed if the corpus grows. |

Plus non-MongoDB:
- `compute_image_embedding(image_url: str) -> list[float]` — wraps Vertex AI `gemini-embedding-2`. Internal to the `find_similar_assets` capability.

### `score_assets_with_vision` + `propose_review_queue` capabilities (was: Step 4 — Operational Prioritization)

Pre-D-021 Step 4 bundled two distinct jobs (Vision scoring + queue assignment) under one workflow step. Post-D-021 these are **two separate capabilities** — scoring is computational/operational; queue assembly is the strategic decision (the one judgment surface per D-021). The wrappers below serve both.

Vision scoring and queue assignment remain temporally distinct: scores are produced first, then queue assembly uses both the scores and the similarity results. Splitting the writes mirrors that ordering. The trace shows "score → score → score → propose-queue (which writes queue assignments)" rather than a single mega-write per asset.

| Wrapper | Internal MCP calls | Used by capability | Notes |
|---|---|---|---|
| `get_assets_for_event(event_id: str, status: str \| None = None) -> list[Asset]` | `assets find` | Multiple | Cross-cutting utility. `score_assets_with_vision` uses it to iterate the batch; `draft_campaigns_for_queue` reuses it with a status filter. Lives in `assets.py`. |
| `save_asset_scores(asset_id: str, scores: AssetScores) -> None` | `assets update-many` | `score_assets_with_vision` | Writes the 5-dimension score block (D-013, D-017). |
| `assign_asset_to_queue(asset_id: str, queue_type: str, product_route: str \| None, reasoning: str) -> None` | `assets update-many` | `propose_review_queue` | Sets `queue_type` ∈ {exploitation, discovery, null}, `product_route`, and per-item `reasoning`. Also transitions status to `"scored"`. *(Signature gains `reasoning` field per D-021's per-item-reasoning requirement.)* |

Plus non-MongoDB:
- The per-image Vertex AI Vision call is **inlined into the `score_assets_with_vision` capability**, not a separate wrapper. *(Pre-D-021 was `score_asset_with_vision(image_url)` — retired per D-021 since there's no reuse case for single-asset scoring outside the capability's iteration.)*

Note on the pre-D-021 spec's `assets.aggregate` for queue grouping: this is now done inside `propose_review_queue` via agent reasoning over results of `get_assets_for_event` + the already-saved similarity lists + scores + narrative. The strategic decision lives in the capability, not in a MongoDB aggregation pipeline.

### `draft_campaigns_for_queue` capability (was: Step 5 — Campaign Draft Creation)

This is the case where bundling is correct. Inserting a campaign draft, linking it to the asset, and queueing it for approval have no independent meaning — a campaign with no approval queue entry is an orphan; an approval entry with no campaign points nowhere; an asset transitioned to `campaign_draft_created` without a campaign is incoherent. The capability makes one atomic write per queued item.

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `submit_campaign_for_review(campaign: CampaignDraft) -> SubmissionResult` | `campaigns insert-many`, `assets update-many`, `approvals insert-many` | Three writes, one atomic domain operation. Returns `{campaign_id, approval_id}`. Called once per queued item. |

Reads reuse cross-cutting utilities:
- `get_event(event_id)` — fetches the event including the narrative written by `build_event_context`.
- `get_assets_for_event(event_id, status="scored")` — fetches queue members ready for drafting.

### `request_human_approval` capability (was: Step 6 — Human-in-the-Loop Review)

The capability `request_human_approval` **is** the ADK `LongRunningFunctionTool` — no separate wrapper layer here. When the operator resolves the gate, internal wrappers handle the resulting state cascade. The decision write is one bundled operation: recording an approval decision without propagating it to the asset's status would leave the asset stranded.

*(Pre-D-021 listed `await_human_approval` as the agent-facing tool; that role is now filled by the `request_human_approval` capability directly. The wrapper is retired.)*

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `get_pending_approvals(limit: int = 50) -> list[Approval]` | `approvals find` | Called by `request_human_approval` to fetch the queue before suspending. Also usable by the operator UI / dashboard directly. |
| `record_approval_decision(approval_id: str, decision: ApprovalDecision) -> None` | `approvals update-many`, `assets update-many` | Called by `request_human_approval` on resume. Bundled write; status cascades to asset. |

### `execute_approved_campaigns` capability (was: Step 7 — Execution)

Execution has a clear temporal split: mark executing → make external calls → record result. These are *not* inseparable — execution can fail partway, and the capability needs to record that distinct state. The result write is bundled across `assets` and `campaigns` because they record the same outcome under two views and have no independent meaning.

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `get_approved_campaigns(limit: int = 50) -> list[ApprovedCampaign]` | `approvals find` joined with `campaigns find` | Returns approved-but-not-yet-executed campaigns. Useful for batch execution and dashboard. |
| `mark_asset_executing(asset_id: str) -> None` | `assets update-many` | State transition before external calls; visible in trace for debugging. |
| `record_execution_result(asset_id: str, campaign_id: str, result: ExecutionResult) -> None` | `assets update-many`, `campaigns update-many` | Bundled — same outcome under two collection views. `ExecutionResult` carries channel results (shopify / printful / social) per `product_route`. |
| `record_execution_failure(asset_id: str, campaign_id: str, error: ExecutionError) -> None` | `assets update-many`, `campaigns update-many` | Failure path; status → rejected with reason. |

Plus non-MongoDB (internal to `execute_approved_campaigns`, not agent-facing):
- `shopify_create_product(...)`, `printful_create_mockup(...)`, `printful_poll_mockup(task_id)`, `simulate_social_post(...)`. The Printful polling is handled inside `execute_approved_campaigns` per `docs/specs/02-architecture.md`.

### `record_outcomes` capability (was: Step 8 — Feedback Loop)

The performance write is the primary runtime concern. The "find best performers" aggregate is forward-looking — it informs *future* runs by potentially seeding vector indexes or analytics views. For the MVP it is more of an analytics tool than a runtime path, useful for demo storytelling ("look — the system has performance data now").

| Wrapper | Internal MCP calls | Notes |
|---|---|---|
| `record_performance(asset_id: str, campaign_id: str, event_id: str, metrics: PerformanceMetrics) -> None` | `performance insert-many` | Primary runtime write. Channel breakdown follows `product_route`. |
| `get_top_performers_by_channel(channel: str, since: datetime \| None = None, limit: int = 20) -> list[Asset]` | `performance aggregate` joined with `assets find` | Analytics view for demo storytelling. Not on the runtime path. Optional for MVP. |

---

## Cross-cutting utilities

A small set of wrappers are used by more than one capability. Listed here so we don't double-count them in per-capability counts.

| Wrapper | Used by capability | Lives in |
|---|---|---|
| `get_event(event_id)` | `build_event_context`, `draft_campaigns_for_queue` (and operator UI) | `events.py` |
| `get_assets_for_event(event_id, status?)` | `score_assets_with_vision`, `propose_review_queue`, `draft_campaigns_for_queue` | `assets.py` |
| `get_pending_approvals(limit)` | `request_human_approval`, operator dashboard | `approvals.py` |
| `get_approved_campaigns(limit)` | `execute_approved_campaigns`, dashboard | `campaigns.py` |

---

## Total wrapper count (internal)

| Collection | MongoDB wrappers |
|---|---|
| `events` | `record_event`, `get_event`, `get_past_events_by_outcome`, `save_event_narrative` (4) |
| `assets` | `record_assets`, `get_assets_for_event`, `vector_search_assets`, `save_asset_embedding`, `save_similar_assets`, `save_asset_scores`, `assign_asset_to_queue`, `mark_asset_executing` (8) |
| `campaigns` | `submit_campaign_for_review`, `get_approved_campaigns`, `record_execution_result`, `record_execution_failure` (4) |
| `approvals` | `record_approval_decision`, `get_pending_approvals` (2) |
| `performance` | `record_performance`, `get_performance_baseline_by_outcome`, `get_top_performers_by_channel` (3) |
| `player_context` | `get_player_context_for_teams` (1) |
| **MongoDB total** | **22** |

| Non-MongoDB helpers (internal to capabilities) | Used by capability |
|---|---|
| `compute_timeliness` | `ingest_event_batch` |
| `compute_image_embedding` | `find_similar_assets` (capability) |
| `shopify_create_product`, `printful_create_mockup`, `printful_poll_mockup`, `simulate_social_post` | `execute_approved_campaigns` |
| **Non-MongoDB total** | **5** |

**The agent's tool surface is 9 capabilities**, not the wrappers below. The ~27 wrappers + helpers below are **internal plumbing** that the capabilities compose. Per D-021, the agent never sees this layer. Per D-019, it never sees raw MCP either. The reasoning surface the agent operates over is the 9 capability docstrings.

*(D-021 retirements from pre-reframe count: `await_human_approval` retired — the `request_human_approval` capability IS the `LongRunningFunctionTool`. `score_asset_with_vision` inlined into the `score_assets_with_vision` capability — no separate wrapper. Rename: `find_similar_assets` wrapper → `vector_search_assets`; the `find_similar_assets` name belongs to the capability.)*

---

## System prompt schema block (conceptual, not field-level)

*(Post-D-021 note: this content is now incorporated into `prompts/v2/agent_system.md` — the active system prompt. The agent picks the right **capability** based on this schema overview + the capability docstrings. The draft block below is preserved as historical reference for what was distilled into v2.)*

D-019 originally called for the system prompt to describe the data model so the agent can pick the right wrapper. Post-D-021 the principle is the same; the granularity is capabilities, not wrappers. Draft block:

```text
Schema overview:
- Event records live in the `events` collection. Each event has a unique event_id.
  Step 1 writes events; Step 2 enriches with a narrative; Steps 3–5 read.
- Image records live in the `assets` collection. Each asset references one event via
  event_id and is the central state document — updated at every step.
- Player biographical facts live in the `player_context` collection, keyed by team
  name. Read in Step 2 for narrative grounding.
- Campaign drafts live in the `campaigns` collection; one per asset-campaign pairing.
- Operator approvals live in the `approvals` collection; one per campaign awaiting
  review. Step 6 writes and reads here.
- Outcome metrics live in the `performance` collection; one document per published
  asset. Step 8 writes; future runs read via the performance-baseline lookup.

The agent does not query MongoDB directly. Use the domain tools (record_event,
record_assets, find_similar_assets, get_player_context_for_teams, etc.) and let
them handle the database details.

Before each tool call, briefly state in one sentence why you are calling it and
what you expect to learn or accomplish. This reasoning is load-bearing for
failure diagnosis during evaluation — it is not stylistic.
```

No collection field names, no filter shapes, no document structure beyond the relational map. The wrappers and their Pydantic types carry the rest.

The "before each tool call, briefly state..." line is required content, not optional. `spike/adk_event_capture.py` confirmed that without it, `gemini-2.5-flash-lite` emits no intermediate reasoning text (0 text parts between tool calls). With it, the model produces a one-sentence rationale before each call, which the eval framework (D-020) uses for failure diagnosis. When the production system prompt is assembled in Step 0 / Step 1, this line must be present and its effect verified once the prompt reaches full size — long prompts sometimes drown out per-call reasoning behavior.

---

## What this displaces from prior plans

*(Pre-D-021 this section captured displacements from the original raw-MCP-in-the-agent design. After Phase A + Phase B item 1 of the D-021 reframe, those displacements have already landed.)*

- ~~**Step 1 plan**~~ — already rewritten in Phase B item 1 (`docs/plans/step-1-event-ingestion.md`). Now describes the `ingest_event_batch` capability with `record_event` + `record_assets` + `compute_timeliness` as internal wrappers.
- ~~**System prompt v1**~~ — already superseded by `prompts/v2/agent_system.md` (Phase A item 6). v1 retained on disk for traceability.
- **Future capability plans (Step 2 onward)** — when written, should follow the pattern set by the Step 1 rewrite: capability surface + internal wrappers + outcome-shaped trace eval.

---

## Open questions for iteration

1. **`save_asset_embedding` + `save_similar_assets` granularity.** Resolved in favor of two wrappers — different lifecycle (embedding is permanent; similarity is recomputable).
2. **Read-side caching.** Player context is read once per event batch (D-016). Cache in-process or hit MongoDB each call? Lean: no cache for MVP.
3. **Wrapper error contract.** Raise vs. return `Result[T, Error]`? Lean: raise. Recovery is the system prompt + LLM reasoning, not branching on result types.
4. **Vector search filter syntax.** `find_similar_assets(channel="poster")` is the simple case. Multi-filter compositions (channel + outcome_type) anticipated? Lean: keep simple now; add kwargs as Step 3 spec firms up.
5. **Where the narrative lives.** D-016 doesn't pin whether the Step 2 narrative is a field on `events` or a separate `narratives` collection. `save_event_narrative` signature assumes the former; revisit when Step 2 is planned.
6. ~~`record_event` vs. `record_event_with_timeliness`~~ — **moot per D-021** (2026-05-26). The pre-D-021 resolution had the agent calling `compute_timeliness` and chaining the value into `record_event` as a separate tool call. Post-D-021, both `compute_timeliness` and `record_event` are internal wrappers used by the `ingest_event_batch` capability — the agent never sees either, so cannot hallucinate the timeliness value. The hybrid-wrapper fallback is no longer needed for this chain. See `docs/plans/strategic-agent-reframe.md` § Step 1 reconciliation.
7. **`get_top_performers_by_channel` cardinality.** Useful for demo? If not used on a workflow path, defer until we know the demo narrative needs it.
