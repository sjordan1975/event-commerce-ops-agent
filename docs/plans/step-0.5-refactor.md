# Step 0.5 — Refactor: D-019 Enforcement Before Step 1

A refactor pass between Step 0 (foundation, merged) and Step 1 (event ingestion, not yet started). Not a workflow step — its purpose is to align the existing Step 0 artifacts with D-019 (domain wrappers over MongoDB MCP supersede raw MCP) and D-020 (evaluation is first-class) before any Step 1 implementation begins.

The driving constraint, restated: **the agent never calls MCP directly.** McpToolset becomes a programmatic client owned by `src/db/client.py` and used by domain wrappers; it is not registered in `agent.tools`. The pattern is verified by `spike/adk_mcp_programmatic.py` (Shape B confirmed).

Existing tests baseline: 4/4 passing in `tests/test_foundation.py` before any changes.

---

## What I scanned

- `src/agent.py` (the only code that wires MCP)
- `prompts/v1/agent_system.md` (currently includes field-level schemas the wrappers will displace)
- `tests/test_foundation.py` + `tests/conftest.py`
- `docs/tasks/step-0-tasks.md` (the original Step 0 acceptance criteria)
- `docs/specs/02-architecture.md` (two McpToolset references)
- `CLAUDE.md` references

---

## Findings, classified by required action

### 1. MUST update — blocks Step 1 implementation

| Artifact | What's wrong now | Required change |
|---|---|---|
| `src/agent.py:38` | `tools: list = [_mcp_toolset()]` puts McpToolset in agent's tool surface | Change to `tools: list = list(extra_tools or [])`. Agent's tool list starts empty. |
| `src/agent.py:20–33` | `_mcp_toolset()` helper lives in agent module | Move to `src/db/client.py` as `MongoMCPClient` (per the verified pattern). Delete from `src/agent.py`. |
| `src/agent.py:1` | Docstring says "wired with McpToolset" | Update to reflect tools-list-from-callers model. |
| `prompts/v1/agent_system.md` lines 11–43 | Field-level `events` and `assets` schema tables. With D-019 these are stale (wrappers carry the contract) and *harmful* — they invite the LLM to construct filter shapes that no tool will accept. | Replace with conceptual schema block from `db-wrapper-inventory.md`. Add the CoT directive ("Before each tool call, briefly state…"). |

### 2. SHOULD update — documentation accuracy

| Artifact | What's wrong | Required change |
|---|---|---|
| `docs/specs/02-architecture.md:10` | `Native ADK adapter; connects MongoDB MCP server as agent tools` | Change "as agent tools" → "as a programmatic client used by domain wrappers (D-019)". |
| `docs/specs/02-architecture.md:298` | `McpToolset(StdioConnectionParams(...)) — connects … as native ADK tools; discovered and proxied automatically` | Add note: "Per D-019, McpToolset is owned by `src/db/client.py` and used programmatically; it is not registered in `agent.tools`." |
| `docs/tasks/step-0-tasks.md` T-0.5 | Acceptance says `build_agent()` returns an agent "with `McpToolset` wired". Historical truth, but stale relative to current code state. | Add a footnote referencing D-019 and Step 1 (where the wiring shifts to the programmatic client). |
| `docs/tasks/step-0-tasks.md` T-0.4 | Acceptance requires the prompt to include "events and assets document field schemas so agent can construct MCP insert documents". Stale — wrappers carry the contract now. | Add the same D-019 footnote. |
| `tests/conftest.py` | `build_valid_event()` / `build_valid_asset()` return plain dicts. Step 0 noted this is temporary. | Replace with Pydantic-model returns when `src/models.py` lands in Step 1. Already in the Step 1 plan; flagging as expected change. |

### 3. SHOULD ADD — D-019 enforcement test

Right now nothing in the test suite *checks* that the agent doesn't have McpToolset in its tools. If someone re-adds it later (rebase, refactor, "fixing" an import), the suite stays green. Worth a small enforcement test:

```python
def test_agent_does_not_expose_mcp_directly():
    """D-019: agent.tools must contain only domain FunctionTools, never McpToolset."""
    from src.agent import build_agent
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

    agent = build_agent()
    for tool in agent.tools:
        assert not isinstance(tool, McpToolset), (
            "McpToolset found in agent.tools — violates D-019. "
            "MongoDB MCP must be used programmatically via src/db/client.py, "
            "not registered as an agent tool."
        )
```

This is the by-construction guarantee D-019 promises. Add it to `tests/test_foundation.py` as part of Step 1's work.

### 4. NO CHANGE NEEDED — verified

| Artifact | Why it's safe |
|---|---|
| `tests/test_foundation.py::test_agent_builds_with_echo_tool` | Asserts `agent is not None` and `agent.name`. Doesn't inspect tool list contents. Keeps passing after the change. |
| `tests/test_foundation.py::test_echo_tool_is_callable` | Tests `_echo` directly. No agent involved. |
| `tests/test_foundation.py::test_echo_tool_wrapped_correctly` | Tests `echo_tool.name == "_echo"`. Unaffected. |
| `tests/test_foundation.py::test_runner_processes_event_stream` | Uses a fully mocked Runner. Never touches MCP. Unaffected. |
| `CLAUDE.md` Tech Stack table | Lists McpToolset as the MCP integration mechanism — still true under D-019. |

### 5. Hidden risk worth naming

`build_agent()` currently calls `_mcp_toolset()` *at agent construction time*. Per the programmatic spike, McpToolset instantiation is cheap (subprocess spawn appears lazy until `get_tools()` is called). But the existing `test_agent_builds_with_echo_tool` test silently depends on this laziness — if McpToolset construction were eager about subprocess setup, every `pytest` run would spawn `npx mongodb-mcp-server`.

After Shape B, this risk evaporates: `build_agent()` doesn't construct McpToolset at all. The MongoDB connection is created on demand inside `MongoMCPClient` only when a wrapper actually needs it. **Net improvement to test hygiene that's worth calling out as a Step 0.5 win.**

---

## Punchlist — six items

| # | Item | File(s) | Blocking? | Notes |
|---|---|---|---|---|
| 1 | Refactor `src/agent.py` — drop `_mcp_toolset()` from `tools=[]`; remove the helper; update docstring | `src/agent.py` | Yes — blocks Step 1 | Code change. Tools list starts empty. |
| 2 | Create `src/db/client.py` with `MongoMCPClient` per the verified pattern | `src/db/client.py`, `src/db/__init__.py` | Yes — blocks Step 1 | Pattern in `db-wrapper-inventory.md` § "Client design". |
| 3 | Update `prompts/v1/agent_system.md` — replace field-level schemas with conceptual block; add CoT directive | `prompts/v1/agent_system.md` | Yes — blocks Step 1 | Conceptual block lives in `db-wrapper-inventory.md`. CoT line is required content per `spike/adk_event_capture.py`. |
| 4 | Add the D-019 enforcement test in `tests/test_foundation.py` | `tests/test_foundation.py` | Yes — blocks Step 1 | One small test (see §3 above). Prevents regression. |
| 5 | Update `docs/specs/02-architecture.md` lines 10 and 298 | `docs/specs/02-architecture.md` | No — documentation hygiene | Spec changes per CLAUDE.md require a `tracking.md` note; D-019 already covers the reasoning, so a one-line cross-reference suffices. |
| 6 | Add footnotes to `docs/tasks/step-0-tasks.md` T-0.4 and T-0.5 referencing D-019 | `docs/tasks/step-0-tasks.md` | No — documentation hygiene | Preserve historical Step 0 acceptance criteria; footnote that D-019 supersedes the wiring described there. |

Items 1–4 must complete before Step 1 implementation work begins. Items 5–6 are documentation hygiene that can land at any point on the Step 0.5 branch (or roll into the Step 1 branch alongside the related code).

---

## Branching

Consistent with the project's branch-per-step workflow (CLAUDE.md): cut `step/0.5-refactor` off `main`, complete the punchlist, verify the test suite (including the new enforcement test) is green, then merge to `main` before opening the Step 1 branch.
