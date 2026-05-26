# Step 0 — Foundation: Task List

## T-0.1: Create pyproject.toml with pinned dependencies

Files: `pyproject.toml`  
Acceptance: Package installs cleanly; `google-adk`, `pydantic`, `python-dotenv`, `pytest` importable from `.venv`  
Verify: `.venv/bin/python -c "import google.adk, pydantic, dotenv, pytest; print('ok')"`

---

## T-0.2: Create package init files

Files: `src/__init__.py`, `tests/__init__.py`  
Acceptance: Both files exist and are empty (or contain only a module docstring); `python -m pytest --collect-only` discovers test files without import errors  
Verify: `.venv/bin/python -m pytest --collect-only`

---

## T-0.3: Create prompt loader

Files: `src/prompt_loader.py`  
Acceptance: `load_prompt(name)` reads `prompts/{PROMPT_VERSION}/{name}.md`; raises `FileNotFoundError` with clear message if file missing; `PROMPT_VERSION` defaults to `"v1"` when env var is unset  
Verify: `.venv/bin/python -c "from src.prompt_loader import load_prompt; print(load_prompt('agent_system')[:50])"`

---

## T-0.4: Create system prompt v1

Files: `prompts/v1/agent_system.md`  
Acceptance: File contains the mission statement (capabilities-available framing, not phase framing); includes `events` and `assets` document field schemas so agent can construct MCP insert documents; includes database name `event_commerce`  
Verify: File readable; manually confirm schema sections present

> Note (D-019, 2026-05-25): field-level schemas in the prompt are superseded by domain wrappers. The Step 0.5 refactor replaces them with a conceptual schema block and adds the CoT directive required for trace-eval diagnosis (D-020).

---

## T-0.5: Create agent shell

Files: `src/agent.py`  
Acceptance: `build_agent()` returns an `LlmAgent` with `McpToolset` wired via `StdioServerParameters`; model read from `GEMINI_MODEL` env var; system prompt loaded via `prompt_loader`; `tools=[]` placeholder ready to receive `FunctionTool` additions in later steps  
Verify: `.venv/bin/python -c "from src.agent import build_agent; print('ok')"`

> Note (D-019, 2026-05-25): McpToolset is no longer wired into `agent.tools`. The Step 0.5 refactor moves it to `src/db/client.py` as a programmatic client (`MongoMCPClient`). `build_agent()`'s tool list starts empty and is extended only with domain `FunctionTool` wrappers as later steps add them.

---

## T-0.6: Create conftest helpers

Files: `tests/conftest.py`  
Acceptance: `build_valid_event()` and `build_valid_asset()` are defined; at Step 0 they return plain `dict` stubs (models not yet defined); they do not raise on import  
Verify: `.venv/bin/python -m pytest --collect-only` (no fixture errors)

---

## T-0.7: Create foundation smoke test

Files: `tests/test_foundation.py`  
Acceptance: Test registers a trivial `echo` `FunctionTool`, sends a message, asserts agent calls it, asserts reasoning trace is non-empty  
Verify: `.venv/bin/python -m pytest tests/test_foundation.py -v`
