# Agentic Model

Companion to `testing-model.md` and `evaluation-strategy.md`. Those cover *how* we test the agent; this one covers *what kind of agent it is* — and, just as importantly, **what kind of agent it is not**.

> **Substantially revised for D-021** (2026-05-26) and then **paid down with implementation by D-024** (2026-05-27). The pre-pivot framing of this doc treated the LlmAgent loop as the agent's macro planning surface and celebrated "emergent step trajectory" as a feature. D-021 rejected that framing conceptually. D-024 implemented the resolution: the agent is now a coordinator `LlmAgent` over a `google.adk.workflow.Workflow` graph. The "Layer 1" section below describes that implementation. The strategic surface is unchanged from D-021 — `propose_review_queue`, added to the workflow as a graph node in Step 5. Full pivot rationale: `docs/plans/strategic-agent-reframe.md`; implementation details + spike validation: `tracking.md` D-024 and `docs/plans/spike-d023-findings.md`.

---

## TL;DR

We are **not** building a free-roaming planner. We are building a **workflow with one judgment surface**, implemented through ADK's `LlmAgent` loop:

- The macro trajectory across the 9 capabilities is mostly known (described in spec, enforced by wrapper preconditions).
- The agent's planning at the macro level is thin — mostly recognizing what to call next given the data state.
- The one place agentic value concentrates is `propose_review_queue` — queue assembly with per-item reasoning. Everything else is mechanical or LLM-at-the-node.

This doc exists so that testing, evaluation, and any future design choices line up against that reality — and do not accidentally re-import the "force agentic planning onto a workflow" anti-pattern that D-021 rejected.

---

## What kind of agent this is — three layers

| Layer | Concern | Where it lives | What the agent decides |
| --- | --- | --- | --- |
| 1. Framework | Mechanism | ADK `LlmAgent` + `Runner` loop | Nothing — this is plumbing |
| 2. Capability composition | Macro trajectory | The sequence of capability invocations | Order among independent operations; when to redraft on `edit_requested`; when to stop |
| 3. Strategy | The one judgment surface | Inside `propose_review_queue` | Queue composition + per-item reasoning |

### Layer 1 — framework (the mechanism)

Per D-024, the implementation is a **coordinator-over-workflow** composition:

```text
Coordinator LlmAgent (mode='chat', gemini-2.5-flash)
├── sub_agent: clarify_event_metadata (LlmAgent, mode='task')   ← bidirectional clarification
├── tool: run_event_pipeline (FunctionTool)                     ← dispatches the workflow
└── tool: request_human_approval (LongRunningFunctionTool)      ← HITL gate

Workflow (graph, run via sub-Runner from the dispatch tool)
  START → ingest_event_batch → build_event_context → [future nodes per step] → END
```

ADK's `Runner` drives the coordinator's chat loop the same way it drives any `LlmAgent`. The coordinator decides: clarify, dispatch, or hand off to approval. When it dispatches, `run_event_pipeline` constructs a sub-`Runner` over the `Workflow` (`google.adk.workflow.Workflow`) with seeded session state and runs the graph deterministically.

The graph enforces execution order structurally — there is no "agent could skip a step" failure mode at the workflow layer anymore. The pre-D-024 single-`LlmAgent` free loop made tool selection a judgment call every turn (including for deterministic steps); the graph removes that surface entirely. This is the "Layer 2 is thin" disposition (described below) made structural rather than prompt-policed.

Sub-Runner-from-tool is the same pattern ADK uses internally (see `AgentTool.run_async` in the ADK source). The shim creates a fresh `InMemorySessionService`, pre-populates state with `images` and `event_metadata`, and iterates the graph. Final session state is returned as the tool result.

### Layer 2 — capability composition (mostly known)

Across tool calls, the agent composes the 9 capabilities to take an event batch from ingestion to published campaigns. **This trajectory is mostly known**, both because the spec describes it (see `docs/specs/02-architecture.md` § ADK Agent Architecture — "capability composition (typical trajectory)" diagram) and because wrapper-level preconditions (`PreconditionError`, see D-021's enforced-vs-emergent split) make the expected trajectory the path of least resistance.

What the agent decides at this layer:

- **Order among independent operations** — `build_event_context`, `find_similar_assets`, `score_assets_with_vision` can be called in any order; each only requires ingestion. The agent picks; outcome is the same.
- **When to redraft on `edit_requested`** — after HITL resumes with operator notes, the agent decides whether to redraft or escalate. `safety-measures.md` caps the number of cycles.
- **When to stop** — terminal text after `record_outcomes` is the typical exit.

What the agent does **not** decide at this layer:

- The macro trajectory itself (workflow-shaped per D-021)
- Whether to skip any required capability (preconditions enforce them)
- Whether to invent new capabilities (it has only what's registered)
- Whether to invoke MongoDB directly (D-019 — never)

This is a thin planning layer — much thinner than a textbook ReAct agent on an open toolbelt. Most "planning" here is recognition: *"I need scores before I can propose a queue, scores aren't done, call `score_assets_with_vision`."* When the agent gets confused, `PreconditionError`'s self-correcting message tells it what to do next (see `strategic-agent-reframe.md` § Enforced vs. emergent).

### Layer 3 — strategy (the one judgment surface)

Inside exactly one capability — `propose_review_queue` — the agent reasons strategically about queue composition:

- Which exploration items to surface (no similarity crutch; pure judgment)
- How to order exploitation items (similarity gave the set; the agent gives the order)
- What per-item reasoning to attach to each surfaced item

This is type-2 agentic value: judgment under bounded ambiguity in a small action space. See `strategic-agent-reframe.md` for the full design.

**This is where agentic value lives.** Layer 1 is the mechanism; layer 2 is the composition; layer 3 is the substance.

---

## Why this framing matters (the anti-pattern)

It is tempting — and was the framing of this doc pre-D-021 — to treat the LlmAgent loop as "where the agent plans the workflow." That framing celebrates emergent step trajectories as if they were a feature. **That framing is wrong for this project**, and re-importing it accidentally is the failure mode this doc is designed to prevent.

Forcing an agentic planning design onto a workflow problem produces concrete costs:

- **Higher token cost** — the agent re-derives the path every run, every time it loses context
- **More failure modes** — the agent could skip or misorder capabilities; trace evals have to assert against an enormous space of "wrong" trajectories
- **Weaker demo story** — visible reasoning gets diluted across mechanical decisions ("I'll call `ingest_event_batch` now because I have images") instead of concentrated where it earns attention ("I'll surface this bench-celebration shot despite no similarity match because it captures the disbelief")
- **Misframed evals** — testing the agent's macro planning is much harder than testing its strategic decision; we would be spending eval budget on the wrong surface

The D-021 reframe concentrates the planning surface where it earns its keep. Layer 2 stays thin on purpose. Layer 3 carries the strategic story.

**Symptom of the anti-pattern resurfacing:** anyone (including future-us) saying *"the agent should decide whether to skip X capability"* or *"the agent should plan the workflow dynamically"* — those are layer-2 expansions that contradict D-021. Push back.

---

## Exit conditions (plumbing — deprioritized)

For completeness — the `LlmAgent` loop exits on:

1. **Terminal text turn.** The LLM emits text without a tool call. Normal exit. After `record_outcomes`, the agent should produce something like *"Published 12 campaigns for wc2026-match-42; 2 deferred; metrics recorded."*
2. **Mid-loop suspension at HITL.** `request_human_approval` returns `None` via `LongRunningFunctionTool`; the runner emits `long_running_tool_ids`; the loop parks. When the caller posts a `FunctionResponse`, the loop resumes. Not an exit — a suspension.
3. **Iteration cap or error.** ADK's max-iterations guardrail terminates runaway loops. Tool exceptions (including `PreconditionError`) feed back into the loop as observations; they do not exit unless the LLM gives up. See `safety-measures.md` for the operational bounds we have not yet committed to.

Pre-D-021 this section worried about *"could the loop spin?"* and *"does the agent know when to stop?"* — both treated as live risks because the agent was framed as a free-roaming planner. Post-D-021, those questions are smaller:

- The loop will not spin on the macro flow — preconditions make the expected trajectory the path of least resistance, and the typical exit (`record_outcomes` → terminal text) is the agent's natural endpoint.
- The agent knows when to stop because the prompt sets a bounded task (ingest this batch, propose a queue, draft, get approval, execute) and the toolbelt runs out of relevant calls after `record_outcomes`.
- The one remaining real risk is the `edit_requested → draft_campaigns_for_queue → request_human_approval` cycle. `safety-measures.md` Gap 1 covers the cap; it lands in Phase C alongside `request_human_approval` itself.

---

## What this means for evaluation

Trace evals operate against the agent's behavior, framed by the three layers:

| Layer | Eval surface | Failure categories from `evaluation-strategy.md` |
| --- | --- | --- |
| 1. Framework | Loop mechanics — tool calls happen, reasoning text is present, loop reaches terminal text or HITL suspension | Reasoning text presence, loop termination |
| 2. Composition | Trajectory — agent called the expected capabilities in a reasonable order; recovered from `PreconditionError` if any; respected data dependencies | Tool selection, tool sequencing (weak — most capabilities are independent), tool arguments, tool-output handling, end-state |
| 3. Strategy | `propose_review_queue` output — queue composition matches event class, per-item reasoning surfaces, agent's strategic choice differs across event types | **Strategy coherence** (new per D-021 — load-bearing for queue-assembly evals) |

The shape of the eval surface flows from which layer a given failure mode lives at:

- A capability that consistently misroutes data is a **layer-2** problem — remediation playbook is prompt → tool docstring → tool surface → hybrid wrapper → model swap.
- A capability that produces incoherent strategy is a **layer-3** problem — same playbook, but the assertions are over queue composition and per-item reasoning, not over tool sequencing.
- A reasoning-text absence is a **layer-1** problem — the CoT directive in the system prompt is load-bearing for diagnosis (per D-020); regression there is a foundation failure.

Different layers, different problems, different evidence. Conflating them is how diagnosis goes wrong.

---

## Cross-references

- `docs/plans/strategic-agent-reframe.md` — D-021 design doc; the capability surface and the one strategic decision this doc presupposes
- `docs/specs/02-architecture.md` § ADK Agent Architecture — the capability composition diagram (typical trajectory) this doc explains
- `prompts/v2/agent_system.md` *(pending Phase A item 6)* — strategist framing for the system prompt; tool docstrings carry the per-capability contracts
- `docs/plans/testing-model.md` — three-category test model (unit / scaffolding / eval); conceptual sibling
- `docs/plans/evaluation-strategy.md` — failure categories (including *strategy coherence* per D-021) and remediation playbook
- `docs/plans/safety-measures.md` — operational bounds (loop cap, spend bound) on the layer-1 mechanism
- `tracking.md` D-019 — wrapper boundary; the agent never calls MongoDB directly
- `tracking.md` D-021 — strategic-agent reframe; the one strategic decision
- `src/agent.py` — confirms single `LlmAgent` implementation
