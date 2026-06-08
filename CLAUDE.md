# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Phase

**Branch `ui/phase-b` (cut from `ui/phase-a`, not yet merged). All 9 capabilities complete; in demo prep. 211 unit tests green (254 total incl. evals).**

**Immediate next:** Deploy — backend on DigitalOcean (new clean Droplet, provisioned via DO MCP), frontend on Vercel. Then demo video. Demo reset between runs = `reset_atlas.py` (sufficient). Pre-demo close tasks in `docs/project-close-hygiene.md`. Deadline: June 11, 2026 @ 2:00 PM PDT.

**Demo corpus: COMPLETE.** 39 images in `data/wc-final/` (Batch 1, France/Croatia 2018 WC Final, 19 images) and `data/wc-draw/` (Batch 2, USA/Wales 2022, 20 images). `data/` is gitignored; restore with `python scripts/prep_demo_corpus.py`. Similarity verified: `QUEUE_EXPLOITATION_SIMILARITY_CUTOFF=0.90` yields 7 exploitation (Batch 1) vs 3 (Batch 2). `QUEUE_MAX_PER_POOL=5` caps each pool post-LLM. See `docs/plans/demo-corpus.md`.

**OPERATIONAL GOTCHA — MCP launch:** use the vendored binary (`MONGODB_MCP_COMMAND` → `src/api/node_modules/.bin/mongodb-mcp-server`), not `npx ...@latest` — npm-registry resolve blocks the event loop and hangs at `create_session`. Not interruptible by `asyncio.wait_for`. See D-035.

**OPERATIONAL GOTCHA — Gemini 503s:** `_drain_queue` timeout is 300s; the SDK retries silently before surfacing, so a hung pipeline can wait several minutes before the UI error panel fires. Do NOT run live evals concurrently. Unit test gate: `pytest tests/ --ignore=tests/evals/`.

**Tier 2 eval:** `tests/evals/test_step_1_trace.py` — coordinator e2e probe, live LLM, run deliberately. Requires `GOOGLE_API_KEY`. Pass-rate posture (`EVAL_REPEAT=20`, ≥95%), transient 503s excluded via `run_with_transient_retry`.

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
| Mockup + publish | Gemini image gen → Shopify staged upload (D-036) |
| Social | Simulated — no live platform API |
| Hosting | Cloud Run |
| Credentials | GCP Secret Manager |

---

## File Structure

```text
project-root/
├── CLAUDE.md             ← this file — session orientation
├── tracking.md           ← decision log (D-000 through current)
├── pyproject.toml
├── package.json          ← root dev script
├── docs/                 ← specs, plans, tasks, and supporting reference docs
├── prompts/              ← versioned system prompts (v1, v2 archived; v3 active)
├── scripts/              ← provisioning, seed, and demo-reset scripts
├── spike/                ← validated ADK spikes
├── src/                  ← Python agent (agent.py, capabilities/, db/, models.py, …)
├── src/api/              ← FastAPI HTTP + SSE bridge (see architecture spec)
├── tests/                ← unit, scaffolding, and eval tests (tests/evals/ for live)
└── ui/                   ← Next.js operator console (see architecture spec)
```

Component-level detail for `src/api/` and `ui/` is in `docs/specs/02-architecture.md § UI Layer`.

Key reference docs:
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
- **Test error paths at every external boundary:** every place the code touches an external system (Gemini API, MongoDB MCP, Shopify, any service or storage) needs a unit test for the error path — not just the happy path. Verify the error surfaces correctly to the output layer (UI `phase: 'error'` + message, or equivalent). See `tests/test_errors.py` (`_format_pipeline_error`) for the pattern.
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
