# Step 7 — HITL Approval + Execution: Task List

> Tasks T-7.1 through T-7.15 implement capabilities **7 (`request_human_approval`)** and **8 (`execute_approved_campaigns`)** plus the **redraft loop** deferred from Step 6 (D-030), per `docs/plans/step-7-hitl.md`. This is the **first step whose capabilities live coordinator-side, not in the workflow graph** — it adds **zero** workflow nodes. The pipeline already ran to `END` and produced drafts (Step 6); the coordinator picks up: suspends on approval, persists per-item decisions, loops redraft on `edit_requested`, then executes the approved set. Execution is **stubbed at the seam** (Option 1) — full capability + status machine built/tested; the four external-API helper bodies return canned payloads, live Shopify/Printful wiring is demo-prep. Tasks follow the plan's § Dependency order (Phase A = the gate, the protocol, the loop, the bound; Phase B = execution).

Prerequisites:
- Step 6 merged to `main` (`draft_campaigns_for_queue` live; assets at `campaign_draft_created`, `campaigns` drafts + `pending` `approvals` written; `submit_campaign_for_review` in `src/db/campaigns.py`).
- Branch `step/7-hitl` cut from `main` (already on it).
- Branch housekeeping commit landed (T-7.0 — see below).
- D-024 scaffolding: `build_coordinator()` registers `run_event_pipeline` (`FunctionTool`) + `request_human_approval` (`LongRunningFunctionTool` **stub**); the clarification sub-agent; the graph is built by `build_pipeline_graph()` (9 nodes, **unchanged this step**).
- HITL primitive validated: `spike/adk_hitl_test.py` + `spike/adk_workflow_hitl_spike.py` claim 2 (suspend on `None`, resume via `FunctionResponse`; the function body does **not** re-run on resume).
- Eval scaffolding from Steps 1–6: `_MockMCPClient` collection-keyed dispatch (write-recording / canned-read); the upstream patch surfaces.

Design decisions baked in (rationale in `docs/plans/step-7-hitl.md` + D-031):
- **The resume-payload spine.** A `LongRunningFunctionTool` body does **not** re-run on resume; the operator's `FunctionResponse.response` goes to the **LLM** as the tool result. So `request_human_approval` is a pure read+gate (no decision writes); a **separate `apply_approval_decisions`** tool persists decisions; `execute`/`redraft` are **pure consumers of persisted Mongo state**. (Corrects `db-wrapper-inventory.md`:210 + the arch diagram — see T-7.0.)
- **Coordinator-plane, not a workflow node** — capabilities 7/8 are coordinator `FunctionTool`s (like `run_event_pipeline`); zero new graph nodes. This is sanctioned **layer-2 composition** on operator input (`agentic-model.md`:56), **not** the anti-pattern, **not** a second strategic node, **not** a post-approval mini-Workflow.
- **Operator-presence assumption** — `LongRunningFunctionTool` suspends (not exits); **no logical timeout**; holds until the operator responds (`01-requirements.md`:149). Honest boundary: in-memory session = process-lifetime-bound. "No timeout" ≠ "no bound" — the *redraft loop* is capped.
- **Resolve-then-execute** (canonical mixed-batch flow) — loop `redraft → request_human_approval` until no `edit_requested` remain (or cap), **then one** `execute_approved_campaigns`. Approvals accumulate across cycles (`status="approved"` items wait; the final execute reads them all from Mongo).
- **Per-item decisions, keyed by `approval_id`** — `{decisions:[{approval_id, decision, reviewer_notes}, ...]}`. Buckets: `approved | rejected | edit_requested`.
- **Display batch grouped by queue half** (exploitation / exploration), per-item narrative + copy + `content_url`, keyed by `approval_id`; grouping is presentational; the *presentation surface* (lightweight app posting the structured `FunctionResponse`) is a **separate demo-prep track**, not Step 7 agent scope.
- **Redraft is a state-consumer** — reads persisted `status="edit_requested"` approvals (notes included); `operator_notes` param retained **only** for D-030 signature stability + unit injection, off the production path.
- **Safety cap (Gap 1) closed this step** — tool-level redraft cap in `tool_context.state` (`MAX_REDRAFT_CYCLES`, default 3) + prompt 3-cycle rule + explicit ADK iteration-cap value.
- **Execution stubbed at the seam — Shopify/Printful only.** `_shopify_create_product` / `_printful_create_mockup` / `_printful_poll_mockup` return canned payloads (live wiring is demo-prep). `_simulate_social_post` is **NOT a stub** — simulation is social's *final form* (Hard Constraint #6), so it writes a real, queryable post package to MongoDB. Printful polling is an **internal async loop** (not a second `LongRunningFunctionTool`); CI never hits live APIs.
- **Channel selection by `product_route`** (not `platform_target`, D-030): poster/tshirt → shopify+printful; social_only / `None` → social.
- **Execution failure is retriable** (MVP): `execution=None` + approval stays `approved` → a re-run re-picks it; no terminal failed state.
- **Eval is two-part** — a deterministic mocked **Tier-1 HITL gate** (the merge gate) + a repetition-based **behavioral protocol probe** (coordinator-level, multi-turn, scripted `FunctionResponse`; not a single-run gate).

---

## T-7.0: Branch housekeeping commit (doc-only)

Doc-only; lands before implementation. Per CLAUDE.md, every `docs/specs/` change needs a `tracking.md` D-entry. **This step's housekeeping is corrective** — two source docs are wrong about HITL resume.

1. **D-031** in `tracking.md` — capabilities 7/8 coordinator-plane + the resume mechanics. All sub-points (a)–(j) from the plan's § Branch housekeeping item 1 (coordinator-plane/zero nodes; resume-payload spine + separate apply-tool + state-consumers; resolve-then-execute; redraft as state-consumer; Gap 1 closed; operator-presence/no-timeout + in-memory boundary; execution stubbed-at-seam + route dispatch; layer-2-not-anti-pattern; the grouped `approval_id`-keyed display batch + presentation-surface-as-separate-track; queue-redo designed-not-built).
2. **`docs/db-wrapper-inventory.md`** — **correct line 210**: `record_approval_decision` is **not** "called by `request_human_approval` on resume" (the function doesn't re-run); it is called by `apply_approval_decisions`. Add `apply_approval_decisions`, `reset_approval_to_pending`, `get_edit_requested_campaigns`; event-scope `get_pending_approvals` / `get_approved_campaigns` signatures.
3. **`docs/specs/02-architecture.md`** — fix the `request_human_approval` MCP-call block (287-293): the gate does the pending **read** + suspend (no decision writes); decision writes belong to `apply_approval_decisions`. Note the Printful poll is an **internal loop**, not a `LongRunningFunctionTool` (reconciles 328 vs 402). Note capabilities 7/8 are coordinator `FunctionTool`s. Flag (do not necessarily fix) the stale tech-stack line 13 ("Single `LlmAgent` … No `Workflow` graph") that predates D-024.
4. **`docs/safety-measures.md`** — mark **Gap 1 closed by Step 7** (tool-level cap + prompt rule + ADK iteration-cap value); record the chosen iteration-cap number.
5. **`docs/specs/01-requirements.md` § capability 7** — confirm the resume contract (per-item decisions **list** keyed by `approval_id`) and that the redraft branch is **implemented here** (closes the D-030 reservation).
6. **`CLAUDE.md` § ADK-Specific Rules** — record the explicit ADK iteration-cap value (per `safety-measures.md`:93).

Verify: `git show <housekeeping-sha> --stat` shows only doc files; no `src/` or `tests/` changes.

---

## Phase A — the gate, the protocol, the loop, the bound

## T-7.1: Add Step 7 models

Files: `src/models.py` (extend), `tests/test_models.py` (extend)
Acceptance:
- `ApprovalDecision(BaseModel)` — `model_config = ConfigDict(extra="forbid")` (boundary validation of operator input). Fields: `approval_id: str`, `decision: Literal["approved", "rejected", "edit_requested"]`, `reviewer_notes: str | None = None`.
- `ApprovedCampaign(BaseModel)` — join view (not persisted, **no** `extra="forbid"` needed). Fields: `approval_id: str`, `campaign: Campaign`, `asset_id: str`, `product_route: str | None`.
- `ExecutionResult(BaseModel)` — fields: `shopify: dict | None = None`, `printful: dict | None = None`, `social: dict | None = None`, `executed_at: str`.
- `ExecutionError(BaseModel)` — fields: `channel: str`, `message: str`, `failed_at: str`.
- Tests: `ApprovalDecision` validates the three decisions, rejects a 4th value, rejects an unknown field (`extra="forbid"`), defaults `reviewer_notes=None`; `ApprovedCampaign` nests a `Campaign`; `ExecutionResult`/`ExecutionError` round-trip; channel dicts default `None`.

Verify: `.venv/bin/python -m pytest tests/test_models.py -v -k "approval_decision or approved_campaign or execution"`

---

## T-7.2: Extend conftest helpers

Files: `tests/conftest.py`
Acceptance: helpers following the `**overrides` pattern:
- `build_valid_approval_decision(**overrides) -> ApprovalDecision` — defaults: `approval_id="apr-1"`, `decision="approved"`, `reviewer_notes=None`.
- `build_valid_approved_campaign(**overrides) -> ApprovedCampaign` — defaults: `approval_id="apr-1"`, `campaign=build_valid_campaign()`, `asset_id="a1"`, `product_route="poster"`.
- `build_valid_execution_result(**overrides) -> ExecutionResult` — defaults: a realistic shopify+printful payload (`shopify={"product_id": "gid://shopify/Product/1", "product_url": "https://demo.myshopify.com/products/x"}`, `printful={"task_id": "t-1", "mockup_url": "https://printful.com/mockups/x.jpg"}`, `social=None`, `executed_at=<iso>`).

Verify: `.venv/bin/python -c "from tests.conftest import build_valid_approval_decision, build_valid_approved_campaign, build_valid_execution_result; from src.models import ApprovalDecision; assert build_valid_approval_decision().decision=='approved'; print('ok')"`

---

## T-7.3: Implement `src/db/approvals.py` wrappers

Files: `src/db/approvals.py` (new), `tests/test_step_7.py` (new file)
Acceptance: three async wrappers (monkeypatch `src.db.approvals.get_client`):
- `get_pending_approvals(event_id: str, limit: int = 50) -> list[Approval]` — `approvals find {event_id, status:"pending"}`. **Event-scoped** (so a second batch can't bleed in). Returns `Approval` models; `_id` never bleeds through.
- `record_approval_decision(approval_id: str, decision: ApprovalDecision) -> None` — **bundled write**: `approvals update-many` (`$set` `status`, `reviewer_notes`, `decided_at=<iso>`) + cascade: `campaigns update-many` (`status` → `approved`/`rejected`; **stays `draft`** for `edit_requested`) + `assets update-many` (`status` → `rejected` **only on reject**; unchanged otherwise). All `"database":"event_commerce"`.
- `reset_approval_to_pending(approval_id: str) -> None` — `approvals update-many` `$set` `status:"pending"`, `reviewer_notes:None` (consumed by redraft), `decided_at:None`.

Unit tests: `get_pending_approvals` filter is event-scoped + `status:"pending"`; `record_approval_decision` issues the right cascade per decision (approved → campaign `approved`, asset unchanged; rejected → campaign `rejected`, asset `rejected`; edit_requested → campaign stays `draft`, asset unchanged; all set approval `status`+`reviewer_notes`+`decided_at`); `reset_approval_to_pending` clears notes + decided_at.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k "pending or decision or reset"`

---

## T-7.4: Implement campaigns read joins

Files: `src/db/campaigns.py` (extend), `tests/test_step_7.py` (extend)
Acceptance: two async read wrappers (the join is `approvals find` then `campaigns find` on the resulting `campaign_id`s):
- `get_approved_campaigns(event_id: str, limit: int = 50) -> list[ApprovedCampaign]` — `approvals find {event_id, status:"approved"}` joined with `campaigns`; **filters `campaign.execution is None`** (so already-executed items aren't re-picked — supports retriable failure + idempotent re-run). Event-scoped.
- `get_edit_requested_campaigns(event_id: str) -> list[ApprovedCampaign]` — `approvals find {event_id, status:"edit_requested"}` joined with `campaigns`; carries `reviewer_notes` (redraft input). Event-scoped.

Unit tests: both filter by `event_id` + the right `status`; `get_approved_campaigns` excludes campaigns with non-null `execution`; the join returns `ApprovedCampaign` carrying the approval id + campaign + product_route.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k "approved_campaigns or edit_requested"`

---

## T-7.5: Flesh `request_human_approval(event_id)` gate + display batch

Files: `src/agent.py` (modify the stub), `tests/test_step_7.py` (extend)
Acceptance: signature changes **`approval_batch` → `event_id`** (the batch is built from persisted state, not passed in — the stub's `drafts`-derived batch carried no `approval_id` to key decisions against).
- `request_human_approval(event_id: str, tool_context: ToolContext)` — `tool_context.actions.skip_summarization = True`.
- Reads `get_pending_approvals(event_id)`; joins each to its campaign copy; builds the **grouped display batch**: `{event_id, exploitation:[...], exploration:[...]}` where each item carries `approval_id`, `campaign_id`, `asset_id`, `content_url`, `queue_rank`, `queue_rationale`, `product_route`, `headline`, `caption`, `hashtags`, `timing_recommendation`. Grouping maps `queue_type` `exploitation → exploitation`, `discovery → exploration`.
- **Returns the batch as the initial long-running response** — `{"status": "pending", "approval_batch": <grouped batch>}` — so the surface renders it; the tool still **suspends** (id in `long_running_tool_ids`) until the decisions `FunctionResponse` arrives. **No decision writes.**
- > **ADK-mechanics confirm (refines the plan's "return None"):** verify that a **non-None** initial return from a `LongRunningFunctionTool` still suspends (emits `long_running_tool_ids`). Confirm with a ~10-line extension to `spike/adk_workflow_hitl_spike.py` claim 2 **or** the Tier-1 assertion in T-7.10. **Fallback if it does not suspend:** return `None` and have the surface fetch the batch via `get_pending_approvals(event_id)` (it already has `event_id`).

Unit tests (mock `get_pending_approvals` + campaign join): the grouped batch has `exploitation`/`exploration` keys; every item carries `approval_id` + `content_url`; `discovery` items land under `exploration`; no Mongo write is issued by this function.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k "request_human_approval or display_batch"`

---

## T-7.6: Implement `apply_approval_decisions` tool

Files: `src/agent.py` (new `FunctionTool`), `tests/test_step_7.py` (extend)
Acceptance: `apply_approval_decisions(decisions: list[dict], tool_context: ToolContext) -> dict` — the **only** place decisions hit Mongo:
- Validate each entry as `ApprovalDecision` (boundary `extra="forbid"`).
- For each, `await record_approval_decision(d.approval_id, d)`.
- Bucket and return `{"approved": [campaign_id...], "rejected": [campaign_id...], "edit_requested": [{approval_id, campaign_id, asset_id, reviewer_notes}...]}`.

Unit tests (mock `record_approval_decision`): a mixed list (1 approved, 1 rejected, 1 edit_requested) calls `record_approval_decision` once per item and returns the three correctly-populated buckets; a malformed decision (`decision="maybe"` or unknown field) raises a validation error before any write.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k apply`

---

## T-7.7: Implement the redraft branch + `overwrite_campaign_draft` + `redraft_campaigns` shim + cap

Files: `src/capabilities/drafts.py` (extend the Step 6 capability), `src/db/campaigns.py` (extend), `src/agent.py` (new `FunctionTool`), `tests/test_step_7.py` (extend)
Acceptance:
- `overwrite_campaign_draft(campaign: Campaign) -> None` (`src/db/campaigns.py`) — `campaigns update-many` `{campaign_id}` replacing `generated_copy` (+ bump `created_at`); asset stays `campaign_draft_created`.
- **Redraft mode in `draft_campaigns_for_queue(event_id, operator_notes=None)`** — when `get_edit_requested_campaigns(event_id)` is non-empty, take the **redraft path** (state-driven; `operator_notes` ignored on the production path, retained for signature stability + unit injection): per item, regenerate copy via `_draft_copy_for_asset` with the persisted `reviewer_notes` injected into `item_context` (e.g. an `operator_revision` line), `await overwrite_campaign_draft(...)`, `await reset_approval_to_pending(approval_id)`. Returns `{event_id, campaign_ids, approval_ids, drafts}` like first-pass. First-pass path (scored + `queue_type`) unchanged.
- `redraft_campaigns(event_id: str, tool_context: ToolContext) -> dict` (`src/agent.py`, `FunctionTool`) — **tool-level cap**: `n = tool_context.state.get("redraft_cycles", 0) + 1`; if `n > MAX_REDRAFT_CYCLES` (env, default 3) return `{"status":"cap_reached","message":"escalate to operator; revision limit hit"}` **without** redrafting; else set `tool_context.state["redraft_cycles"] = n` and `return await draft_campaigns_for_queue(event_id)`.

Unit tests: redraft mode reads `edit_requested`, injects notes, overwrites copy, resets approvals to pending (not first-pass when edit_requested present); first-pass still works when no edit_requested; `overwrite_campaign_draft` issues the `campaigns` update; the cap refuses on the `(MAX_REDRAFT_CYCLES+1)`-th call and increments state otherwise.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k "redraft or overwrite or cap"`

---

## T-7.8: Coordinator prompt protocol + register Phase-A tools + caps/env

Files: `prompts/v3/coordinator_system.md` (substantial edit — first-class), `src/agent.py` (register tools, iteration cap), `.env.template` + `README.md` (env)
Acceptance:
- **Coordinator prompt** gains the dedicated **post-approval protocol** section (plan § "Coordinator prompt"): after drafts, call `request_human_approval`; **always `apply_approval_decisions` before anything else**; branch (resolve-then-execute) — `edit_requested` present → `redraft_campaigns(event_id)` then back to `request_human_approval`; else → `execute_approved_campaigns(event_id)` **once**; **3-cycle redraft limit** then escalate; never publish without an explicit per-item approval. (Port the 3-cycle rule from `prompts/v2/agent_system.md`.)
- **Register** `apply_approval_decisions` + `redraft_campaigns` as `FunctionTool`s in `build_coordinator()` (alongside the existing `run_event_pipeline` + `request_human_approval`). `execute_approved_campaigns` is registered in Phase B (T-7.12).
- **`MAX_REDRAFT_CYCLES`** env (default `3`) added to `.env.template` + README.
- **Explicit ADK iteration-cap** value chosen and set on the coordinator `Runner`/agent; recorded in `CLAUDE.md` (T-7.0 item 6) + `safety-measures.md` (T-7.0 item 4).

Verify: `.venv/bin/python -c "from src.agent import build_coordinator; build_coordinator(); print('ok')"` (coordinator builds with the new tools) and a prompt-content check (`apply` before execute/redraft; 3-cycle rule present).

---

## T-7.9: Extend trace-eval scaffolding (HITL resume + combined handlers)

Files: `tests/evals/conftest.py` (modify)
Acceptance: per the plan's § Eval scaffolding — coordinator-level, multi-turn, with a scripted operator response:
1. **Mock-handler discipline (confirmed memory — clobber rule).** Register **one combined** `(find, approvals)` handler that branches on the `status` in the filter (`pending` / `approved` / `edit_requested`) and **one combined** `(update-many, approvals)` handler — never two handlers for the same `(tool, collection)`. Same for `campaigns` (find covers the approved/edit_requested joins; update-many covers cascade + overwrite + execution writes).
2. **Seed approvals/campaigns** for one event spanning routes (poster/tshirt/social_only) and statuses, so apply → branch → execute have real state to read.
3. **Scripted decisions `FunctionResponse` helper** — builds a `Content` with a `function_response` part carrying `{"decisions": [ {approval_id, decision, reviewer_notes}, ... ]}` (a **list**), matching the suspended tool-call id. Parameterizable to all-approved / mixed / with-edit_requested.
4. **External-helper seam (Phase B)** — patch the three Shopify/Printful helpers (`_shopify_create_product` / `_printful_create_mockup` / `_printful_poll_mockup`) to canned payloads. `_simulate_social_post` does a **real** package write — let it write through the mock MCP client (recorded) so the test asserts the social package was persisted, rather than patching it away.

Verify: `.venv/bin/python -m pytest tests/evals/test_mock_dispatch.py -v` (existing green) + a new mock-dispatch test asserting the combined `approvals` handler returns the right docs per `status` filter and the scripted decisions `FunctionResponse` round-trips a list.

---

## T-7.10: Tier 1 — HITL gate (deterministic, mocked) — Phase A scope

Files: `tests/evals/test_step_7_trace.py` (new)
Acceptance: a full coordinator round-trip with external helpers stubbed, `_draft_copy_for_asset` mocked, approvals/campaigns seeded. Dispatch → suspend at `request_human_approval` → resume with a **decisions list** → assert (Phase A subset of the plan's T1):
- (T1-a) the coordinator received the list and called `apply_approval_decisions` with **all N** items (the list-payload round-trip — the new ADK fact).
- (T1-b) `apply` persisted correctly: approvals → right statuses + `reviewer_notes` + `decided_at`; cascade to campaign/asset (rejected → `rejected`; edit_requested → notes persisted, campaign stays `draft`).
- (T1-c) branch correctness — a batch with `edit_requested` → `redraft_campaigns` then back to `request_human_approval` (no execute yet); an all-approved batch → exactly one `execute_approved_campaigns` (stub assertion deferred to T-7.14 if execution not yet registered — assert the branch decision here).
- (T1-e) **cap survives suspend/resume** — `redraft_cycles` in session state increments across a park; the 4th redraft is refused.
- (T1-f) reasoning text present (CoT); `apply` always precedes `execute`/`redraft`.
- Also confirms the T-7.5 ADK-mechanics question: suspension occurred with the non-None initial return (`long_running_tool_ids` emitted). On failure `dump_trace()`.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_7_trace.py -v` (offline, no `GOOGLE_API_KEY`). **Phase-A portion of the gate `main` stays green against.**

---

## Phase B — execution behind seams

## T-7.11: Implement execution write wrappers

Files: `src/db/campaigns.py` (extend), `src/db/assets.py` (extend), `tests/test_step_7.py` (extend)
Acceptance:
- `mark_asset_executing(asset_id: str) -> None` (`assets.py`) — `assets update-many` `$set` `status:"executing"`. Visible in trace.
- `record_execution_result(asset_id: str, campaign_id: str, result: ExecutionResult) -> None` (`campaigns.py`) — **bundled**: `assets update-many` (`status:"published"` + `published_urls` = the channels present in `result`) + `campaigns update-many` (`status:"executed"` + `execution` = `result.model_dump(mode="json")`).
- `record_execution_failure(asset_id: str, campaign_id: str, error: ExecutionError) -> None` (`campaigns.py`) — **retriable** (MVP): leaves `campaign.execution = None` (so a re-run re-picks via `get_approved_campaigns`), reverts asset from `executing` (e.g. back to `campaign_draft_created`), records the error detail; approval stays `approved`. **Not** a terminal failed state.

Unit tests: `mark_asset_executing` sets `executing`; `record_execution_result` writes `published` + `published_urls` (only channels present) + campaign `executed` + `execution`; `record_execution_failure` leaves `execution=None` and asset re-pickable.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k "executing or execution_result or execution_failure"`

---

## T-7.12: Implement `execute_approved_campaigns` capability + stubbed helpers

Files: `src/capabilities/execution.py` (new), `tests/test_step_7.py` (extend)
Acceptance:
- **Three stubbed external helpers** (Shopify/Printful — the live/mock seam; live wiring is demo-prep): `_shopify_create_product(...) -> dict`, `_printful_create_mockup(...) -> dict` (returns a `task_id`), `_printful_poll_mockup(task_id) -> dict` (returns `completed` + `mockup_url`) — canned payloads this step. **One REAL helper:** `_simulate_social_post(...) -> dict` writes the complete social post package to MongoDB — simulation is social's **final form** (Hard Constraint #6), **not** a stub-pending-live. Printful create+poll wrapped in an **internal async poll loop** (bounded retries + timeout) — **not** a second `LongRunningFunctionTool`; the stub returns `completed` immediately but the loop structure is real (demo-prep swaps only the Shopify/Printful helper bodies).
- `execute_approved_campaigns(event_id: str, tool_context: ToolContext) -> dict` — `approved = await get_approved_campaigns(event_id)`; per item: `await mark_asset_executing(asset_id)`; **dispatch by `product_route`** (poster/tshirt → `_shopify_create_product` + Printful poll-loop → `ExecutionResult` with shopify+printful; social_only / `None` → `_simulate_social_post` → `ExecutionResult` with social); `await record_execution_result(...)`; on a helper exception `await record_execution_failure(...)`. Returns `{event_id, executed:[...], failed:[...]}`.

Unit tests (stub helpers; mock `get_approved_campaigns` + the write wrappers): route dispatch (poster/tshirt → shopify+printful keys; social_only → social key); success → `record_execution_result`; a helper raising → `record_execution_failure` (and execution remains retriable); `mark_asset_executing` called before external calls; the Printful poll loop terminates.

Verify: `.venv/bin/python -m pytest tests/test_step_7.py -v -k "execute or route_dispatch or poll"`

---

## T-7.13: Register `execute_approved_campaigns` + extend coordinator branch

Files: `src/agent.py` (register), `prompts/v3/coordinator_system.md` (extend the branch)
Acceptance:
- Register `execute_approved_campaigns` as a `FunctionTool` in `build_coordinator()`.
- Coordinator prompt's resolve-then-execute branch now calls `execute_approved_campaigns(event_id)` once when no `edit_requested` remain (completing the protocol from T-7.8).

Verify: `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` (coordinator builds with all Step 7 tools; graph still 9 nodes) and `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` (full unit suite green; no regression).

---

## T-7.14: Tier 1 — full HITL + execution gate (deterministic, mocked, CI ship gate)

Files: `tests/evals/test_step_7_trace.py` (extend T-7.10 through execution)
Acceptance: extends the T-7.10 round-trip to completion with execution stubbed. Adds:
- (T1-c, completed) all-approved batch → exactly one `execute_approved_campaigns`.
- (T1-d) execution end-state — approved items → asset `published` + `published_urls`, campaign `executed` + `execution`; route dispatch correct (poster/tshirt → shopify+printful keys; social_only → social key); rejected items never executed.
- (T1, mixed) a mixed batch resolves: edit_requested loops (redraft → re-approve), then the final execute picks up **all accumulated** approvals (round-1 approvals not lost).
- On failure `dump_trace()`. Deterministic → single run authoritative; zero live calls.

Verify: `.venv/bin/python -m pytest tests/evals/test_step_7_trace.py -v` (offline, no API key). **This is the gate `main` stays green against.**

---

## T-7.15: Behavioral branch probe (live, repetition — NOT a single-run gate)

Files: `tests/evals/test_step_7_protocol.py` (new)
Acceptance: the behavioral risk is the **coordinator protocol on flash** — does it reliably (a) `apply` before `execute`/`redraft`, (b) redraft-then-loop on `edit_requested`, (c) execute-once otherwise, (d) stop at the cap? Run with the project's pass-rate posture (`EVAL_REPEAT=20`, ≥95%). `GOOGLE_API_KEY` required; external helpers still stubbed (no live Shopify/Printful). On failure climb the remediation ladder **prompt-first** (the protocol section is the first rung). On `dump_trace()`. **Not a merge gate** — Tier 1 + the unit suite are.

Verify: `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_7_protocol.py -v` (requires `GOOGLE_API_KEY`).

---

## Verification checkpoints (rollup — Tier 1 + unit suite must pass before merge)

| After | Command | Must pass |
| --- | --- | --- |
| T-7.1 | `.venv/bin/python -m pytest tests/test_models.py -v -k "approval_decision or approved_campaign or execution"` | `ApprovalDecision` validates/rejects; transfer models round-trip. |
| T-7.3 | `.venv/bin/python -m pytest tests/test_step_7.py -v -k "pending or decision or reset"` | Event-scoped pending read; `record_approval_decision` cascade per decision; reset clears notes. |
| T-7.4 | `.venv/bin/python -m pytest tests/test_step_7.py -v -k "approved_campaigns or edit_requested"` | Join filters by event + status; approved excludes executed. |
| T-7.5 / T-7.6 | `.venv/bin/python -m pytest tests/test_step_7.py -v -k "request_human_approval or apply"` | Grouped `approval_id`-keyed batch, no writes from the gate; `apply` buckets + persists every item. |
| T-7.7 | `.venv/bin/python -m pytest tests/test_step_7.py -v -k "redraft or overwrite or cap"` | Redraft state-consumer path; cap refuses past `MAX_REDRAFT_CYCLES`. |
| T-7.8 / T-7.13 (wiring) | `.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"` | Coordinator builds with all Step 7 tools; graph still 9 nodes. |
| T-7.11 / T-7.12 | `.venv/bin/python -m pytest tests/test_step_7.py -v -k "execut or route_dispatch or poll"` | Status machine + route dispatch; failure retriable; poll loop terminates. |
| Full unit suite | `.venv/bin/python -m pytest tests/ -v --ignore=tests/evals` | All Step 0–7 unit tests green; no regression. |
| **Tier 1 — HITL + execution gate (CI)** | `.venv/bin/python -m pytest tests/evals/test_step_7_trace.py -v` | Deterministic; (T1-a)–(T1-f) incl. list round-trip, apply-before-branch, cap-survives-suspend, execution end-state; offline, no API key. The gate `main` stays green against. |
| Behavioral probe (deliberate) | `EVAL_REPEAT=20 .venv/bin/python -m pytest tests/evals/test_step_7_protocol.py -v` | Protocol order pass rate ≥ 95%/20. Requires `GOOGLE_API_KEY`. **Not a merge gate.** |

---

## Notes on task granularity

- **Phase A / Phase B split** is the plan's: A delivers the gate + protocol + redraft loop + safety cap (the agentic substance + the spine); B delivers execution behind seams. The branch can sit green at the end of Phase A (HITL works; execution is the next half).
- **T-7.3 / T-7.4 split**: write-side cascade (`approvals.py`) vs. read-side joins (`campaigns.py`) — different collections, different failure modes.
- **T-7.5 / T-7.6 split** is the **spine made concrete**: the gate (`request_human_approval`, no writes) and the persister (`apply_approval_decisions`, all the writes) are deliberately separate tools because the function does not re-run on resume.
- **T-7.7 bundles** the redraft branch + `overwrite_campaign_draft` + the `redraft_campaigns` shim + the cap — one logical "redraft loop" unit (the cap is meaningless without the shim; the shim is meaningless without the branch).
- **T-7.9 dedicated scaffolding task** mirrors Step 6's T-6.11: coordinator-level multi-turn eval needs the combined handlers + scripted `FunctionResponse` before the Tier-1 eval can run.
- **T-7.10 / T-7.14 split**: Phase-A Tier-1 (HITL + branch + cap, no execution) lets the branch land green before Phase B; T-7.14 extends the same file through execution. One eval artifact, two landing points.
- **T-7.15 split from Tier 1**: the deterministic mocked gate (mechanics) vs. the live repetition probe (the flash protocol) are different artifacts, commands, and CI posture — the behavioral risk is the coordinator protocol, which is what repetition measures.

---

## What is intentionally not in this step

- **No live Shopify/Printful.** Helpers stubbed at the seam (Option 1); CI never hits live APIs; live wiring + the `mockup_url` demo artifact are a tracked **demo-prep** task. The internal Printful poll-loop structure is real so only the helper body swaps.
- **No queue-level redo.** Item-level copy `edit_requested` is built; rebuilding the *selection* (back to Step 5 with operator steering) is **designed-not-built** (a future `repropose_queue` tool — D-031), with no retrofit cost to the per-item contract.
- **No new workflow nodes.** Capabilities 7/8 are coordinator `FunctionTool`s; `build_pipeline_graph()` stays at 9 nodes.
- **No `record_outcomes`.** Capability 9 is Step 8; it reads the executed campaigns / published assets this step writes.
- **No persistent session service.** In-memory for the demo; the operator-presence "no timeout" is process-lifetime-bound (the durable-resume swap is a Cloud Run / enterprise concern).
- **No second strategic node, no post-approval mini-Workflow.** The post-HITL branch is layer-2 composition on operator input; revisit a post-approval workflow only when `record_outcomes` adds a second ordered deterministic step.
- **No `operator_notes` on the production redraft path.** Redraft reads persisted `edit_requested` notes from Mongo; the param is retained only for signature stability + unit injection.
- **No free-text decision parsing in the agent.** The structured decisions `FunctionResponse` is constructed by the surface (lightweight app); terminal free-text chat is a fallback with that parsing caveat noted.
