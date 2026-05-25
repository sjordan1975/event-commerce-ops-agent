# Step 0 — Foundation: Implementation Plan

## What this delivers

The infrastructure everything else runs on: project scaffold, the `LlmAgent` shell with `McpToolset`, the prompt loader, and the initial mission-oriented system prompt. No step logic lives here. Verification: agent boots, can call a trivial echo tool, and its reasoning trace is visible in the terminal.

---

## The planning agent distinction

This is **not** a `SequentialAgent` pipeline. The `LlmAgent` runs a ReAct loop — it reasons about what tool to call next based on current state, calls it, observes the result, and plans the next action. The sequence emerges from the agent's reasoning, not from code.

**Consequence for the system prompt:** it must express the GOAL and available tools, not the steps. A prompt that says "step 1: ingest, step 2: score" produces a script runner. The mission prompt looks like:

> "You are a real-time event commerce operations agent. Your mission is to transform raw event photos from live sports events into approved, published commerce campaigns before the attention window closes. Available tools cover photo ingestion, semantic similarity search against past campaign performance, asset scoring, campaign drafting, human approval, and execution across Shopify, Printful, and social channels. Plan and execute what's needed for the situation."

The LLM reasons its way to the correct sequence because the tool docstrings express preconditions (can't score before ingesting; can't draft before scoring). The sequence is implied by tool design, not instructed by the prompt.

---

## Components

| # | Component | File | Purpose |
|---|-----------|------|---------|
| 1 | Project scaffold | `pyproject.toml`, `src/__init__.py`, `tests/__init__.py`, `.env.template` | Package structure, pinned deps |
| 2 | Prompt loader | `src/prompt_loader.py` | Loads versioned prompt files; reads `PROMPT_VERSION` env var |
| 3 | System prompt (v1) | `prompts/v1/agent_system.md` | Mission-oriented goal prompt — expresses WHAT, not HOW |
| 4 | Agent shell | `src/agent.py` | `LlmAgent` + `McpToolset` wiring; tools list starts empty, grows each step |
| 5 | Conftest helpers | `tests/conftest.py` | `build_valid_event()`, `build_valid_asset()` — reused across all test files |
| 6 | Foundation smoke test | `tests/test_foundation.py` | Agent boots; echo tool is called; reasoning trace is non-empty |

---

## Dependency order

1. **Project scaffold** — `pyproject.toml` with pinned `google-adk`, `pydantic`, `python-dotenv`, `pytest`
2. **Prompt loader** — pure file I/O, no agent dependency
3. **System prompt** — written before the agent shell so it can be loaded immediately
4. **Agent shell** — wires `LlmAgent(model=GEMINI_MODEL, tools=[], instruction=prompt_loader.load(...))` + `McpToolset`; tools list is empty at Step 0 and grows as steps are built
5. **Conftest** — `build_valid_event()` and `build_valid_asset()` need models (from Step 1) to be fully useful, but the helpers can be stubbed now
6. **Smoke test** — registers a trivial `echo` FunctionTool, sends a message, asserts agent calls it and reasoning trace is non-empty

---

## Prompt engineering notes

The system prompt is iterated across the build — it's not finalized at Step 0. Lifecycle:

| Phase | Prompt state |
|-------|-------------|
| Step 0 | Mission statement + empty tools list |
| Steps 1–4 | Add tool descriptions as each is registered; verify agent calls them in logical order |
| Step 5–6 | Tune HITL behavior — agent must not proceed past `request_approval` until human responds |
| Step 7–8 | Tune execution + feedback loop behavior |
| Demo prep | Final iteration — verify reasoning trace tells the right story for judges |

**Prompt versioning:** `PROMPT_VERSION=v1` env var. Bump to `v2`, `v3` etc. as you iterate. Old versions stay in `prompts/` for rollback. Never edit a version in place — always write a new one.

---

## Evals (MVP scope)

Full eval frameworks are a production concern. For this project, evals are two things:

1. **Tool-call assertion tests** (in `tests/`): mock at the `Runner` boundary; assert that for a given input the agent called the expected tool within N turns. Written as steps are built. These are the "did it plan correctly?" check.

2. **End-to-end trace inspection** (manual, during demo prep): run the agent against seed data from `scripts/seed_mongodb.py`; inspect the reasoning trace in the terminal. Check for: skipped steps, double-ingestion, missed HITL gate, incoherent routing decisions.

The demo trace IS the eval for judge purposes. ADK surfaces the full reasoning trace natively — use it.

---

## Env vars required

```
GOOGLE_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-lite
PROMPT_VERSION=v1
MONGODB_URI=...
```

---

## Verification checkpoints

| After | Command | Must pass |
|-------|---------|-----------|
| Scaffold | `.venv/bin/python -m pytest --collect-only` | Test files discovered, no import errors |
| Agent shell | `.venv/bin/python -c "from src.agent import build_agent; print('ok')"` | Imports cleanly |
| Smoke test | `.venv/bin/python -m pytest tests/test_foundation.py -v` | Agent boots, calls echo tool, trace non-empty |
