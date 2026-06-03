# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Phase

**All 9 capabilities complete; in the back-third (demo prep). On `ui/phase-b` (cut from `ui/phase-a`, not yet merged). Phase A complete and committed: MCP health badge (boot sequence red→amber→green, mid-pipeline blip, 3-state honest degradation), credential-gated preview cards (`mode: 'live'|'preview'`, `PreviewBadge`, poster frame + AI t-shirt mockup via Gemini 3 Pro image, `photo_url`/`mockup_url` split on `ShopifyProduct`). Phase B started: real `/health` poll wired (env-var gate `NEXT_PUBLIC_API_URL`; unset → Phase A mock falls back), `src/images.py` consolidates all image-source handling (local path, https://, gs://; `image_as_part` + `list_images`), `list_images` coordinator tool added, coordinator prompt updated, `google-cloud-storage` added to deps. 206 unit tests green.**

**`test_step_1_trace.py` — the coordinator e2e probe, reclassified to **Tier 2 (live), per D-020** (FIXED + live-verified, `1 passed`).** It is the only eval that drives the real coordinator (NL → `run_event_pipeline` → the full 9-node graph → present results → advance to the HITL gate). Because the coordinator *is* a live LLM it **cannot be deterministic**, so it is a **Tier-2 live probe, NOT the offline CI merge gate** ("no live model in the CI gate"): requires `GOOGLE_API_KEY`, run deliberately, pass-rate posture (`EVAL_REPEAT=20`, ≥95%) with transient 503s retried-then-excluded via `run_with_transient_retry` (so the rate measures coordinator judgment, not Gemini uptime). Ingest's deterministic coverage lives in `tests/test_step_1.py` (unit) + every other step's Tier-1 pipeline eval. The prior "known failure" diagnosis (eval scaffold mishandles the coordinator tool sequence) was wrong — root cause was **seed rot**: `_seed_mock_for_full_pipeline` covered a 2-node pipeline while the graph grew to 9, so downstream nodes hit unseeded reads and aborted. Fixes: (1) seed every node's reads (Step-6 scaffolding + empty canned ReviewQueue + `_stub_internal_llms` for narrative/copy LLMs + `approvals.get_client` patch so `request_human_approval` suspends cleanly); (2) exceptions **propagate** so `run_with_transient_retry` classifies them — a seed-gap `PreconditionError` (non-transient) re-raises and names the aborting node, while `_assert_pipeline_completed` backstops the no-exception "coordinator never dispatched" case; (3) assertion (f) relaxed from `is_final` text to "non-empty text after `run_event_pipeline` returns" (the natural terminus is an HITL suspension, not a final-text turn). **Operational:** under a Gemini 503 storm google-genai retries with backoff, so a throttled run *silently hangs for minutes* with 0-byte output — do NOT launch live evals concurrently. Unit tests (deterministic, no live calls, the actual CI gate): `pytest tests/ --ignore=tests/evals/`.

**OPERATIONAL GOTCHA:** launch the MCP server via the vendored pinned binary (`MONGODB_MCP_COMMAND` → `src/api/node_modules/.bin/mongodb-mcp-server`), **not** `npx ...@latest` — the npm-registry resolve blocks the event loop and hangs in restricted-egress environments (sandboxes, Cloud Run without egress). The hang is at `create_session` and is **not** interruptible by `asyncio.wait_for`. See `docs/plans/mcp-connection-lifecycle.md` / D-035.

**Phase B SSE wire-up complete (live-verified, full Turn 1 + Turn 2 browser run passing).** `ui/src/lib/live-api.ts` replaces fixture simulation when `NEXT_PUBLIC_API_URL` is set (gate: `ui/.env`, gitignored). Backend: `.venv/bin/python3 -m uvicorn src.api.server:app --port 8000`. Known bugs fixed in this session: (1) `scores` key missing from `_build_approval_item_payload` return → crash on `item.scores.quality`; (2) React 18 automatic batching collapsed all SSE events into one render — fixed with `setTimeout(r,0)` yield in `readSseStream`. **Live Agent Feed sidebar (StreamingNotices)** punted: shows 9 capability result-summary notices (same as ActivityTimeline, different widget). True granular sub-step chatter (DB wrapper calls, per-asset ops) deferred — would require instrumenting `src/db/` wrappers; low-risk defer given deadline.

**Seed corpus enriched (committed `dde8607`).** 24 API-verified Wikimedia CC images added via `--add-images` mode; corpus now 64 assets (19 poster / 14 tshirt / 31 social_only). All 4 seed events have ≥4 posters and ≥2 tshirts. `reset_atlas.py` expected counts updated to 64. Commerce routing and server-side mockup generation **live-verified** in browser this session: tshirt path routed correctly from enriched corpus, `GET /api/mockup/{asset_id}` returned a Gemini-generated t-shirt mockup on the fly. Routing mechanics documented in `docs/specs/01-requirements.md` § "Routing mechanics (precise)" — exploitation routes are code-locked (similarity-weighted plurality vote, LLM cannot override); discovery routes are LLM judgment from live Step 4 vision scores.

**Immediate next:** live Shopify/Printful wiring — swap the execution stubs in Step 7 with real API calls. Then: approval UI, Cloud Run deploy, demo video. Demo reset between runs = `reset_atlas.py` (sufficient; no separate prep script needed). Pre-demo close tasks in `docs/project-close-hygiene.md`. Deadline: June 11, 2026 @ 2:00 PM PDT.

Step 8 = `record_outcomes` (capability 9, the **last**) — a **thin, honest coda** (D-032). Second coordinator-plane step; **zero new workflow nodes** (graph stays at 9). Registers `record_outcomes` as a coordinator `FunctionTool`. Writes one **provenance** `performance` row per published asset (true linkage + 7-day window anchor + `metrics: null`, `metrics_status: "pending_sync"`) — **no fabricated metrics**; real outcomes are synced async by an external process (enterprise path). **Descope, not removal** (Hard Constraint #1; blessed at the human gate). **No LLM call, no external API call** — first purely-computational coordinator capability. Key design: (1) **spine protection** — pending docs excluded from `aggregate_performance_for_events` (a retro into Step-2-owned code, filter `$ne "pending_sync"`) so the Step-2 baseline stays measured-only; (2) **execute+record stay sibling coordinator tools, not a post-approval Workflow** (resolves D-031(h)) — D-023 order-tension mitigated by prompt + tool-level no-op guard; (3) **idempotent upsert** by `(asset_id, event_id)` (deviation from inventoried `insert-many`); (4) `get_top_performers_by_channel` **deferred** (designed-not-built). Reference: `docs/plans/step-8-outcomes.md`, `docs/tasks/step-8-tasks.md`, `tracking.md` D-032, `docs/_step-8-notes.md`.

Step 7 = capabilities 7 (`request_human_approval`) + 8 (`execute_approved_campaigns`) + the redraft loop (closes D-030's `operator_notes` reservation). **First coordinator-plane step — zero new workflow nodes.** Spine (D-031): the HITL `LongRunningFunctionTool` body does **not** re-run on resume → a separate `apply_approval_decisions` tool persists the per-item decisions list, and `execute`/`redraft` are pure consumers of persisted Mongo state (corrects `db-wrapper-inventory.md`:210 + arch 287-293). Execution **stubbed at the seam** (Option 1 — live Shopify/Printful is demo-prep). Gap 1 closed (redraft cap 3 + ADK iteration cap 30). Plan phased A (gate+protocol+loop+cap) / B (execution). Reference: `docs/plans/step-7-hitl.md`, `docs/tasks/step-7-tasks.md`, `tracking.md` D-031. Known deviations: `apply_approval_decisions` buckets return `approval_id` (not `campaign_id`); T-7.15 behavioral probe deferred to demo-prep; async LRFT suspend verified by ADK source inspection (not a running spike). 153 unit tests + 11 Tier-1 eval assertions green.

Step 6 = `draft_campaigns_for_queue` (capability 6) — complete (merged `d2205c7`). 118 unit tests + Tier 1 gate + grounding probe all green.

Key Step 6 decisions baked in (D-030): **a `FunctionNode`, NOT a second `LlmAgent` node** (`02-architecture.md`:373 — Step 5 stays the one strategic node). Returns to the Steps 2/4 internal-`genai` pattern: per-item `_draft_copy_for_asset` (mirror Step 4's `_score_asset_with_vision`, `response_schema=GeneratedCopy`), bundled `submit_campaign_for_review` (new `src/db/campaigns.py`: campaigns insert + assets status→`campaign_draft_created`+link + approvals pending insert; **not** a transaction; no `reviewer_notes` input). **Reuse `GEMINI_MODEL`** (flash-lite — `build_event_context` precedent; **no new env var**). `event_id`-based signature reading the persisted queue from Mongo (D-022). Route→fields: poster/tshirt→shopify, social_only→(null,social), None→social defensively. **Redraft deferred to Step 7** (`operator_notes` reserved/unused). **Zero surfaced assets = valid empty result**, not a precondition error. Copy grounds at event-narrative + identity (`detected_subjects` = identity/commercial signal); **no raw image to the copy LLM**; GROUNDING GUARD in the prompt (name only `detected_subjects`, no invented actions).

**Eval is Step-4-shaped (not Step-5's two-tier):** Tier 1 (`test_step_6_trace.py`, `_draft_copy_for_asset` mocked, deterministic, single-run) is the **merge gate**. Because `_MockMCPClient` is write-recording / canned-read, Tier 1 **pre-seeds route-spanning queue-bearing assets** (Step 6 is the first node that reads state a prior node wrote — load-bearing scaffolding decision, T-6.11). Optional live **grounding probe** (`test_step_6_grounding.py`) is a quality check, **not** a pass-rate gate.

Reference: `docs/plans/step-6-drafts.md`, `docs/tasks/step-6-tasks.md`, `tracking.md` D-030. The enterprise-trajectory + grounding-granularity discussion (operator-framed→data-derived autonomy; perception-vs-composition; MongoDB-MCP-as-state-backbone partner framing) is captured in the plan's § Enterprise trajectory + D-030 (j)/(k).

Update the above before ending each session — it is the single source of truth for session orientation.  
Deadline: June 11, 2026 @ 2:00 PM PDT.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Gemini (Vertex AI) |
| Embeddings | `gemini-embedding-2` (Vertex AI, 3072-dim multimodal) |
| Orchestration | Google ADK v2.1 |
| MCP integration | `McpToolset` (built into ADK) |
| Database / state | MongoDB Atlas |
| Ecommerce | Shopify GraphQL Admin API (Partners dev store) |
| Print-on-demand | Printful REST API |
| Social | Simulated — no live platform API |
| Hosting | Cloud Run |
| Credentials | GCP Secret Manager |

---

## File Structure

```text
project-root/
├── CLAUDE.md                    ← this file — index only
├── tracking.md                  ← decision log
├── docs/specs/
│   ├── 00-overview.md          ← vision, origin, positioning, demo narrative
│   ├── 01-requirements.md      ← functional spec, 9 capabilities + queue assembly (D-021), MVP scope
│   └── 02-architecture.md      ← system design, MongoDB schemas, MCP call list, ADK architecture
├── docs/agentic-model.md        ← agent loop shape, exit conditions, HITL framing, three-layer model
├── docs/db-wrapper-inventory.md ← MongoDB wrapper signatures, per-step ownership
├── docs/evaluation-strategy.md  ← six failure categories, trace-eval model, remediation ladder
├── docs/safety-measures.md      ← loop bound + spend bound
├── docs/spike-d023-findings.md  ← D-023 spike results (superseded by D-024)
├── docs/strategic-agent-reframe.md ← D-021 capability surface, queue assembly, propagation plan
├── docs/testing-model.md        ← three-category test model (unit / scaffolding / eval)
├── docs/workflow.md             ← per-step workflow and phase gates
├── docs/plans/                  ← per-step implementation plans (step-*.md only)
├── docs/tasks/                  ← per-step atomic task lists (one file per step)
├── spike/                       ← validated ADK spikes (adk_hitl_test.py, adk_mcp_raw_test.py, adk_event_capture.py, adk_workflow_hitl_spike.py [D-024])
├── scripts/                     ← provisioning and seed scripts (setup_mongodb.py, seed_mongodb.py)
├── src/                         ← agent code (agent.py, prompt_loader.py, db/, models)
├── tests/                       ← test suite (test_foundation.py, expanded each capability)
└── prompts/                     ← versioned system prompts (v1 + v2 archived as pre-D-024 snapshots; v3 active per D-024)
```

Planning documents (historical, superseded by docs/specs/):
- `docs/rapid_agent_hackathon_spec.md` — hackathon rules reference; do not modify

---

## Hard Constraints

Do not violate these without explicit user decision. Full rationale in `docs/specs/02-architecture.md`.

1. Do not remove capabilities or collapse the queue-assembly decision into a heuristic (D-021; was "Do not simplify or merge the 8-step workflow")
2. MongoDB is the partner MCP — do not substitute another vector store
3. Gemini is the LLM — do not use OpenAI, Anthropic, or non-GCP models
4. `gemini-embedding-2` is the embedding model — do not use Voyage AI or non-GCP alternatives
5. Google ADK v2.1 is the orchestration layer — do not substitute LangGraph or Agent Builder without updating D-005 and the architecture spec
6. Social posting is simulated — do not wire a live Instagram, X/Twitter, or Buffer API
7. Do not rewrite tests to make them pass — fix the implementation
8. Do not expand MVP scope without explicit user approval

---

## Build Commands

```bash
# Install dependencies
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Run all tests
.venv/bin/python -m pytest tests/ -v

# Run a single test file
.venv/bin/python -m pytest tests/test_foundation.py -v

# Verify agent shell imports (coordinator + workflow per D-024)
.venv/bin/python -c "from src.agent import build_coordinator, build_workflow; build_coordinator(); build_workflow(); print('ok')"

# Run a spike
.venv/bin/python spike/adk_mcp_raw_test.py
```

---

## Spec Documents

| File | Contents |
|------|----------|
| `docs/specs/00-overview.md` | Vision, origin story, positioning, demo narrative, scoring philosophy, risks |
| `docs/specs/01-requirements.md` | Functional spec, 9 capabilities + queue assembly (D-021), MVP scope, non-goals, demo flow, judging alignment |
| `docs/specs/02-architecture.md` | Full tech stack, MongoDB schemas, MCP call list, external integrations, ADK agent architecture |

---

## Decision Log

See `tracking.md` for all architectural decisions (D-000 through D-025) with full rationale.

Key decisions: MongoDB over Elastic (D-001), Google ADK v2.1 over LangGraph (D-005, confirmed by spike D-011), `gemini-embedding-2` over Voyage AI (D-006), social simulation over live API (D-007), logistics reframe (D-014), two-queue exploration/exploitation (D-015, exploration default updated by D-021), Step 2 event narrative + `player_context` RAG (D-016), Step 4 dual-job (D-017), raw McpToolset spike (D-018), domain wrappers over MongoDB MCP supersede raw (D-019), evaluation is first-class engineering (D-020), **strategic-agent reframe: procedural → strategist with queue assembly (D-021)**, **graph-orchestrated coordinator-over-workflow architecture (D-024, paying off D-023)**, **Step 3 vector-search configuration + embedding auth path (D-025)**.

**Every commit that changes `docs/specs/` must add or update a D-entry in `tracking.md`.**

---

## Build Practices

### Development Approach
- Build incrementally — one capability end-to-end before moving to the next (per D-021's capability surface)
- Fix root causes, not symptoms; never suppress errors to unblock tests
- Test utility scripts with both happy path and intentional failure inputs before wiring into agent capabilities
- **Verify tooling before use:** Before using any CLI flag, plugin, or library method, confirm it is listed in `pyproject.toml` (or equivalent manifest). Do not reach for something from habit without checking it is installed in this project.
- **Default to standard, latest-stable approaches:** Use well-supported, contemporary, widely-adopted tools and library patterns unless there is a specific documented reason to do otherwise. No experimental flags or clever one-offs without justification.
- **Specs reference the source of truth; they do not duplicate it.** When a spec/doc would restate code-owned detail — type shapes, component decomposition, exact field names — reference the code instead (e.g. `ui/src/lib/types.ts`, the component files); you cannot drift from what you don't restate. Specs capture intent, contracts, and behavior, not implementation the code is the authority on. When implementation diverges from a spec (often a genuine improvement), reconcile the spec **in the same change** — an unreconciled spec is a bug, not a stale nicety. See `spec-code-drift` memory.

### Testing (unit + scaffolding — distinct from evals)
- **TDD for all core logic:** Pydantic models, scoring functions, prompt construction, output parsing
- **Stub pattern:** stubs raise `NotImplementedError`; tests fail on assertions, not imports — never use `pytest.importorskip` for core modules
- **Conftest helpers:** `build_valid_asset()`, `build_valid_campaign()`, etc. — return valid model instances for reuse across test files
- **LLM scaffolding tests:** validate prompt structure and output parsing without live API calls; mock at the `Runner` boundary, not inside agent logic
- Test runner: `pytest` — run with `.venv/bin/python -m pytest`
- **Framing:** see `docs/testing-model.md` for the three-category model (unit / scaffolding / eval) — defines the boundary between this section and § Evaluation

### Evaluation (agentic behavior — distinct from unit tests)
- **Trace-based evals are required for every capability** — not optional, not "if we have time" (D-020). Live under `tests/evals/`.
- **A passing smoke test is not evidence the system works.** Repetition matters: pass rate ≥ 95% across 20 runs per capability is the ship gate. A test that passes 5/5 in CI but 18/20 manually is a flake we should be nervous about.
- **When an eval surfaces a partial result or failure, run the remediation playbook top-to-bottom before declaring "acceptable":** prompt language → tool docstring → tool surface → hybrid wrapper → model swap. Never settle on "acceptable for MVP" with a cheap rung untried. See `docs/evaluation-strategy.md`.
- **Failure traces must include LLM reasoning text.** The "Before each tool call, briefly state why" directive in the system prompt is load-bearing for this — confirmed by `spike/adk_event_capture.py`. Do not remove it without re-verifying reasoning text still surfaces under the full production prompt.
- **Six failure categories to assert on:** tool selection, tool sequencing (weaker now that most capabilities are independent — see D-021), tool arguments, tool-output handling (the hallucination case), end-state, and **strategy coherence** (queue assembly: does the composition match the event class? per D-021 — load-bearing for `propose_review_queue` evals).

### Type Safety and Models
- Type hints on all function signatures (parameters + return types)
- Pydantic models for all MongoDB document shapes — live in `src/models.py`
- Validate at system boundaries (Shopify response, Printful response, MongoDB reads) — trust internal ADK/Pydantic guarantees elsewhere

### ADK-Specific Rules
- `LongRunningFunctionTool` is required for all HITL — do not use plain `FunctionTool` for `request_human_approval`
- **HITL resume (D-031):** a `LongRunningFunctionTool` body does **not** re-run on resume — the operator's `FunctionResponse` goes to the coordinator LLM, not the function. So `request_human_approval` is a pure read+suspend gate; a separate `apply_approval_decisions` tool persists the per-item decisions list; `execute_approved_campaigns` and redraft re-read persisted Mongo state. Capabilities 7/8 are coordinator `FunctionTool`s, **not** workflow nodes.
- **Loop bound (D-031, closes `safety-measures.md` Gap 1):** the `edit_requested` redraft loop is capped by `MAX_REDRAFT_CYCLES` (env, default **3**, enforced in `tool_context.state` by `redraft_campaigns`) + the coordinator prompt's 3-cycle rule; the coordinator runner's explicit **ADK iteration cap is 30** (`COORDINATOR_MAX_LLM_CALLS` in `src/agent.py` — pass as `RunConfig(max_llm_calls=30)` to `run_async`; framework backstop; the load-bearing bound is the redraft cap).
- **Two model env vars per D-024:** `GEMINI_COORDINATOR_MODEL` (default: `gemini-2.5-flash`) for the chat-mode coordinator and any task-mode sub-agents; `GEMINI_MODEL` (default: `gemini-2.5-flash-lite`) for workflow nodes and any internal-LLM helpers like `build_event_context`. Never hardcode model names. Flash-lite is unreliable at the coordinator's delegate-vs-dispatch decision points — keep that role on flash.
- **Workflow primitive (D-024):** orchestration is via `google.adk.workflow.Workflow` with `FunctionNode`s, not `SequentialAgent` (deprecated in ADK v2.1). The graph is built by `src/capabilities/__init__.py:build_pipeline_graph()`. Each new step extends the graph by adding nodes and an edge — the agent shell does not change.
- **Coordinator dispatches the workflow via a `FunctionTool` shim** (`run_event_pipeline` in `src/agent.py`). The shim spins up a sub-`Runner` with pre-populated session state. `Workflow` extends `BaseNode`, not `BaseAgent`, so `AgentTool` cannot wrap it.
- The OTel `ValueError: Token was created in a different Context` warning on generator exit is cosmetic — do not attempt to fix it
- **Framing:** see `docs/agentic-model.md` for what kind of agent this is (coordinator chat loop + workflow graph + one strategic node + bidirectional clarification + HITL). Pair with `docs/strategic-agent-reframe.md` for the capability surface and the one strategic decision (`propose_review_queue`).

### Prompts
- All LLM prompts live in `prompts/` as versioned subdirectories (e.g. `prompts/v3/`) — do not inline prompts in agent logic
- A prompt loader utility (`src/prompt_loader.py`) handles file I/O and version selection — agent logic calls the loader, never reads prompt files directly
- Active prompt version set via `PROMPT_VERSION` env var; default is `v3` (D-024). Prior versions (`v1`, `v2`) are archived snapshots — see `prompts/v2/ARCHIVED.md`
- v3 active prompts: `coordinator_system.md` (coordinator LlmAgent), `clarification_system.md` (task-mode sub-agent), `build_event_context.md` (capability-internal narrative prompt). No `agent_system.md` in v3 — that orphaned file lives only in the v2 archive.

### Code Style
- Docstrings on public interfaces only — one line max; no multi-paragraph docstrings
- No comments unless the WHY is non-obvious (hidden constraint, ADK-specific workaround, non-obvious invariant)

---

## Quality Standards

- **Readable:** Clear variable names, logical structure
- **Maintainable:** Modular functions, separated concerns
- **Tested:** Validated against expected behavior
- **Documented:** Comments explain non-obvious logic
- **Idiomatic:** Uses Pythonic patterns and libraries — clean and straightforward; avoid clever one-liners that sacrifice readability; prioritize clarity over brevity
- **Consistent:** Follow the same patterns and styles across the project for coherence and ease of understanding
- **Error-Resilient:** Anticipate and handle potential failure points gracefully, especially at external API and data source boundaries; avoid crashes from unhandled exceptions

---

## Git

- Never add `Co-Authored-By` or any Claude attribution to commit messages

### Branch-per-step workflow

- `main` is always green — all verification checkpoints in the step's task file pass before merging
- One branch per step: `step/{N}-{name}` (e.g. `step/0-foundation`, `step/1-ingestion`)
- Each branch carries its own `docs/plans/step-N-*.md` and `docs/tasks/step-N-tasks.md` alongside the implementation code — plans and tasks are living documents that may be updated if implementation reveals spec gaps
- Merge to `main` only when all `Verify:` commands in the task file pass
- Update the "Next action" line in `CLAUDE.md` as part of the merge commit
- Never commit implementation code directly to `main`
- Plans/tasks files for future steps exist on disk (uncommitted) until their branch is cut
