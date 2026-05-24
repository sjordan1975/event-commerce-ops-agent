# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Phase

**Pre-code — all decisions locked, implementation not started.**

Next action: Provision MongoDB Atlas cluster + configure MCP server.  
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
├── tracking.md                  ← decision log + next actions
├── docs/specs/
│   ├── 00-overview.md          ← vision, origin, positioning, demo narrative
│   ├── 01-requirements.md      ← functional spec, 8-step workflow, MVP scope
│   └── 02-architecture.md      ← system design, MongoDB schemas, MCP call list
└── [code — not yet created]
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

*(Not yet established — project is pre-code.)*

---

## Spec Documents

| File | Contents |
|------|----------|
| `docs/specs/00-overview.md` | Vision, origin story, positioning, demo narrative, scoring philosophy, risks |
| `docs/specs/01-requirements.md` | Functional spec, 8-step workflow, MVP scope, non-goals, demo flow, judging alignment |
| `docs/specs/02-architecture.md` | Full tech stack, MongoDB schemas, MCP call list, external integrations, ADK agent architecture |

---

## Decision Log

See `tracking.md` for all architectural decisions (D-000 through D-010) with full rationale.

Key decisions: MongoDB over Elastic (D-001), Google ADK v2.1 over LangGraph (D-005, confirmed by spike D-011), `gemini-embedding-2` over Voyage AI (D-006), social simulation over live API (D-007).

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
