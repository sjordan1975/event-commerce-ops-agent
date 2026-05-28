# v2 prompts — archived (pre-D-024 snapshot)

This directory is a **historical snapshot** of the prompt set as it existed under the pre-D-024 single-`LlmAgent` architecture (D-021 strategic-agent reframe). It is no longer loaded by any code. The active prompt set is `prompts/v3/` per D-024.

## What's in here

- `agent_system.md` — the single-agent system prompt from before D-024. Carried "operator drives the workflow — only proceed when instructed" anti-chaining language. Under D-024 the workflow graph enforces order structurally, so this prompt is no longer needed. Kept here as a snapshot of what was solving the chaining problem before the architecture change.
- `coordinator_system.md`, `clarification_system.md`, `build_event_context.md` — these three were added to v2 during the D-024 refactor (mid-version) and then carried forward verbatim to v3. They are the active prompts of the post-D-024 architecture. Their presence in v2 is incidental; the canonical copies live in v3.

## Why v2 was kept rather than deleted

Same precedent as v1: when D-021 introduced v2, v1 was kept on disk for traceability. When D-024 introduced v3, v2 is kept on disk for the same reason. Anyone who wants to understand the pre-pivot prompt set can read this directory; anyone who wants to understand the active prompts should read `prompts/v3/`.

## Do not load this directory

`src/prompt_loader.py` defaults to `PROMPT_VERSION=v3`. Setting `PROMPT_VERSION=v2` would resurrect the orphaned `agent_system.md` for `load_prompt("agent_system")` calls — but no code path makes such calls anymore, so even an explicit override would not change behavior. The override would only matter if you were inspecting these prompts manually.

See `tracking.md` D-024 for the full rationale of the architectural pivot.
