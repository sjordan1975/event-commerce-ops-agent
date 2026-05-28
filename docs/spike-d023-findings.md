# Spike: D-023 Pivot Findings

**Date:** 2026-05-27
**Branch:** `step/3-similarity`
**Spike file:** `spike/adk_workflow_hitl_spike.py`
**Background plan:** `/Users/sjordan/.claude/plans/do-a-plan-for-snazzy-engelbart.md`

This write-up answers: *can we move from the single-`LlmAgent` free-loop pattern to a graph-orchestrated `Workflow` + chat-coordinator + task-mode clarification sub-agent shape?* The spike validates three load-bearing primitives. The findings drive the go/no-go on the refactor.

---

## Results — all three claims validated

| # | Claim | Result | Notes |
| --- | --- | --- | --- |
| 1 | `Workflow` with `FunctionNode`s + `LlmAgent(mode='single_turn')` node runs end-to-end | **PASS** | FunctionNodes fire, state passes through, LlmAgent node produces strategic-decision text. Event author for function nodes is the parent workflow name (`spike_workflow`); LlmAgent nodes use their own name. |
| 2 | `LongRunningFunctionTool` from inside an LlmAgent coordinator suspends and resumes | **PASS** | `long_running_tool_ids` set on suspension; resume via `FunctionResponse` produces final text. Same shape as the pre-existing `spike/adk_hitl_test.py` — confirms HITL pattern survives in ADK v2.1 and is not blocked by anything in the proposed refactor. |
| 3 | LlmAgent coordinator with task-mode sub-agent handles multi-turn clarification | **PASS** *(model-dependent — see caveat)* | Coordinator delegates to `clarify_event_metadata`; task agent asks "What was the outcome type?"; operator answers; task agent calls `finish_task('upset')`; coordinator picks up the result and emits expected text. End-to-end multi-turn loop works. |

**Overall recommendation: GO on the refactor.** The three primitives required by the target architecture all work in ADK v2.1 as documented in the source.

---

## Important caveat — claim 3 is model-dependent

The clarification delegation in claim 3 **does not work reliably with `gemini-2.5-flash-lite`** (the current project default in `CLAUDE.md`). Across three runs with flash-lite and increasingly strict prompts, the coordinator hallucinated an `outcome_type` value (`extra_time`, `upset`, then `regulation_win`) rather than delegating to the clarification sub-agent. The clarification primitive itself works — the very first run showed the task agent producing the right question — but the coordinator's *decision to delegate* is not reliable at flash-lite.

Bumping to `gemini-2.5-flash` produced clean delegation on the first attempt:

```
[TURN 1] ambiguous batch
  [clarify_event_metadata] What was the outcome type (upset, draw, extra_time, regulation_win)?

[TURN 2] operator answers 'It was an upset.'
  [clarify_event_metadata function_call] name=finish_task args={'result': 'upset'}
  [clarify_event_metadata function_response] name=finish_task response={'result': 'Task completed.'}
  [user function_response] name=clarify_event_metadata response={'result': 'upset'}
  [coordinator_claim_3 text] Ready to ingest with outcome_type=upset
```

**Implication for the refactor:** the coordinator agent should run on `gemini-2.5-flash` (or stronger), not `gemini-2.5-flash-lite`. Workflow nodes (the deterministic capabilities and the strategic-decision LlmAgent) can stay on flash-lite. This is a small operational adjustment, not a blocker.

This finding also vindicates the user's `feedback_evals_remediation_ladder` memory: the cheap rungs (prompt-tightening, docstring-tightening, message-cue-removal) all failed to fix the delegation; the model-swap rung fixed it on the first try. The right fix was the right rung.

---

## What did NOT fail — degradation paths not needed

The plan named documented degradation paths for each claim. None are needed:

- **Claim 1 fallback (coordinator-only orchestration without Workflow):** not invoked. Workflow + FunctionNode + LlmAgent integration is clean.
- **Claim 2 fallback (HITL coordinator-side only):** not invoked. HITL works identically to the pre-refactor pattern.
- **Claim 3 fallback (coordinator-handled clarification, no task sub-agent):** not invoked. Task-mode delegation works with a sufficient model.

---

## Operational notes from running the spike

- **Cosmetic OTel error.** `ValueError: Token was created in a different Context` appears at the start of the run, attached to "Root node coordinator_claim_2 was cancelled." It is harmless — same family of error CLAUDE.md documents under § ADK-Specific Rules. Do not attempt to fix.
- **Event authors in `Workflow`.** FunctionNode-produced events carry the parent `Workflow.name` as `event.author`, not the function name. LlmAgent nodes inside a Workflow carry their own name. The spike's first iteration assumed function name and failed its own assertions; the fix was to use closure-captured flags. **For the refactor, eval scaffolding that filters events by author needs to know this.**
- **State propagation between FunctionNodes works as documented.** `mock_ingest` wrote `event_id` to `ctx.state`; `mock_build_context` read `event_id` from its parameter (auto-bound from state). Zero extra wiring needed.
- **`sub_agents` auto-wires `_TaskAgentTool`.** Adding a `mode='task'` sub-agent to a coordinator's `sub_agents` list automatically creates the task-delegation FC tool — no manual `AgentTool` wrapping required.

---

## What this means for the refactor

The plan's target architecture stands:

```
Coordinator LlmAgent (mode='chat', model=gemini-2.5-flash)
├── sub_agent: clarify_event_metadata (mode='task')   ← clarification
├── tool: request_human_approval (LongRunningFunctionTool)  ← HITL approval
└── tool/dispatch: Workflow (deterministic pipeline + strategic node)
```

One remaining design question for the refactor — **not blocking, but worth recording**: how does the coordinator dispatch the `Workflow`? `Workflow` extends `BaseNode`, not `BaseAgent`, so `AgentTool(workflow)` is not a valid wrap. Two options:

1. **Wrap the workflow as a `FunctionTool`** that internally creates a sub-Runner and drives the workflow. Adds a small amount of glue code; preserves coordinator-driven dispatch.
2. **Invert the relationship:** make the `Workflow` the top-level runnable and put the clarification + HITL stages as `LlmAgent` nodes inside the workflow's graph (using `mode='chat'` or `mode='task'` nodes via `ctx.run_node` dynamic dispatch per `_workflow.py:200-219`).

Option 1 matches the plan's diagram and keeps human-presence operations conceptually above the workflow. Option 2 is more graph-pure but moves the chat surface into the graph. **Recommendation:** option 1 for the refactor; option 2 is a possible later optimization.

---

## Go/no-go recommendation

**GO on the refactor**, with three documented adjustments:

1. **Coordinator model:** `gemini-2.5-flash`, not `gemini-2.5-flash-lite`. Workflow nodes can stay on flash-lite. Add a separate env var or constant for the coordinator model.
2. **Workflow dispatch from coordinator:** wrap the `Workflow` as a `FunctionTool` (option 1 above); record as a design decision (D-024 or similar).
3. **Eval scaffolding:** any event filtering by `event.author` needs to handle `event.author == <workflow_name>` for FunctionNode events.

The refactor scope as described in the plan (`src/agent.py` rewrite, `src/capabilities/*` wrapping change, prompt split, doc updates, N=20 gate re-run) stands unchanged from the plan. None of the spike findings require the plan to be reshaped.

Total spike effort spent: ~1 hour (under the 1-day plan budget). The plan's projected 1–2 days for the refactor remains the right estimate.
