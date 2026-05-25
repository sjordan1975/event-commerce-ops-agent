# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Phase

**Implementation in progress.**

Next action: Implement Step 1 (Event Ingestion) — see `docs/plans/step-1-event-ingestion.md`, tasks in `docs/tasks/step-1-tasks.md`  
Update this line before ending each session — it is the single source of truth for session orientation.  
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
│   ├── 01-requirements.md      ← functional spec, 8-step workflow, MVP scope
│   └── 02-architecture.md      ← system design, MongoDB schemas, MCP call list
├── docs/plans/                  ← per-step implementation plans (one file per step)
├── docs/tasks/                  ← per-step atomic task lists (one file per step)
├── spike/                       ← validated ADK spikes (adk_hitl_test.py, adk_mcp_raw_test.py)
├── scripts/                     ← provisioning and seed scripts (setup_mongodb.py, seed_mongodb.py)
├── src/                         ← agent code (agent.py, prompt_loader.py, models added each step)
├── tests/                       ← test suite (test_foundation.py, expanded each step)
└── prompts/v1/                  ← versioned system prompt (agent_system.md)
```

Planning documents (historical, superseded by docs/specs/):
- `rapid_agent_hackathon_spec.md` — hackathon rules reference; do not modify

---

## Hard Constraints

Do not violate these without explicit user decision. Full rationale in `docs/specs/02-architecture.md`.

1. Do not simplify or merge the 8-step workflow
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

# Verify agent shell imports
.venv/bin/python -c "from src.agent import build_agent; print('ok')"

# Run a spike
.venv/bin/python spike/adk_mcp_raw_test.py
```

---

## Spec Documents

| File | Contents |
|------|----------|
| `docs/specs/00-overview.md` | Vision, origin story, positioning, demo narrative, scoring philosophy, risks |
| `docs/specs/01-requirements.md` | Functional spec, 8-step workflow, MVP scope, non-goals, demo flow, judging alignment |
| `docs/specs/02-architecture.md` | Full tech stack, MongoDB schemas, MCP call list, external integrations, ADK agent architecture |

---

## Decision Log

See `tracking.md` for all architectural decisions (D-000 through D-020) with full rationale.

Key decisions: MongoDB over Elastic (D-001), Google ADK v2.1 over LangGraph (D-005, confirmed by spike D-011), `gemini-embedding-2` over Voyage AI (D-006), social simulation over live API (D-007), logistics reframe (D-014), two-queue exploration/exploitation (D-015), Step 2 event narrative + `player_context` RAG (D-016), Step 4 dual-job (D-017), raw McpToolset spike (D-018), domain wrappers over MongoDB MCP supersede raw (D-019), evaluation is first-class engineering (D-020).

**Every commit that changes `docs/specs/` must add or update a D-entry in `tracking.md`.**

---

## Build Practices

### Development Approach
- Build incrementally — one workflow step end-to-end before moving to the next
- Fix root causes, not symptoms; never suppress errors to unblock tests
- Test utility scripts with both happy path and intentional failure inputs before wiring into agent steps

### Testing
- **TDD for all core logic:** Pydantic models, scoring functions, prompt construction, output parsing
- **Stub pattern:** stubs raise `NotImplementedError`; tests fail on assertions, not imports — never use `pytest.importorskip` for core modules
- **Conftest helpers:** `build_valid_asset()`, `build_valid_campaign()`, etc. — return valid model instances for reuse across test files
- **LLM scaffolding tests:** validate prompt structure and output parsing without live API calls; mock at the `Runner` boundary, not inside agent logic
- Test runner: `pytest` — run with `.venv/bin/python -m pytest`

### Evaluation (agentic behavior — distinct from unit tests)
- **Trace-based evals are required for every workflow step** — not optional, not "if we have time" (D-020). Live under `tests/evals/`.
- **A passing smoke test is not evidence the system works.** Repetition matters: pass rate ≥ 95% across 20 runs per step is the ship gate. A test that passes 5/5 in CI but 18/20 manually is a flake we should be nervous about.
- **When an eval surfaces a partial result or failure, run the remediation playbook top-to-bottom before declaring "acceptable":** prompt language → tool docstring → tool surface → hybrid wrapper → model swap. Never settle on "acceptable for MVP" with a cheap rung untried. See `docs/plans/evaluation-strategy.md`.
- **Failure traces must include LLM reasoning text.** The "Before each tool call, briefly state why" directive in the system prompt is load-bearing for this — confirmed by `spike/adk_event_capture.py`. Do not remove it without re-verifying reasoning text still surfaces under the full production prompt.
- **Five failure categories to assert on per step:** tool selection, tool sequencing, tool arguments, tool-output handling (the hallucination case), end-state.

### Type Safety and Models
- Type hints on all function signatures (parameters + return types)
- Pydantic models for all MongoDB document shapes — live in `src/models.py`
- Validate at system boundaries (Shopify response, Printful response, MongoDB reads) — trust internal ADK/Pydantic guarantees elsewhere

### ADK-Specific Rules
- `LongRunningFunctionTool` is required for all HITL steps — do not use plain `FunctionTool` for Step 6
- Model configured via `GEMINI_MODEL` env var (default: `gemini-2.5-flash-lite`) — never hardcode
- The OTel `ValueError: Token was created in a different Context` warning on generator exit is cosmetic — do not attempt to fix it

### Prompts
- All LLM prompts live in `prompts/` as versioned subdirectories (e.g. `prompts/v1/`) — do not inline prompts in agent logic
- A prompt loader utility (`src/prompt_loader.py`) handles file I/O and version selection — agent logic calls the loader, never reads prompt files directly
- Active prompt version set via `PROMPT_VERSION` env var (e.g. `PROMPT_VERSION=v1`)

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
