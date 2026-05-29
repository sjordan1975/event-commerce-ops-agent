# Safety Measures (Followups)

Companion to `agentic-model.md`. That doc establishes that we run a single `LlmAgent` loop composing 9 capabilities, with terminal text after `record_outcomes` as the typical exit. This doc tracks the operational safety measures (loop iteration bound, token/spend bound) we have **not yet fully decided on** for that loop — partially mitigated post-D-021 but not yet closed.

Captured to make the gaps visible; not yet scoped into a capability's task list.

---

## What D-021 changed (blast radius reduced, gaps remain)

Pre-D-021, this doc captured open-ended risks: the agent could spin in many ways across an unbounded planning surface. Post-D-021, the surface is much smaller — most of the gaps below have *partial* mitigations that did not exist before:

| Concern | Pre-reframe | Post-reframe |
| --- | --- | --- |
| Agent spins by calling wrong tools | Real risk — open-ended planning across 20+ tools | Largely retired — `PreconditionError`'s self-correcting messages eliminate misordering as a spin source; capability surface is 9 (small combinatorial space) |
| Agent spins on `edit_requested` redraft | No cap anywhere | Partially mitigated — `prompts/v2/agent_system.md` hardcodes a 3-cycle escalation rule. ADK's overall iteration cap still needs explicit setting. |
| Agent wanders past natural stopping point | Risk grows with toolbelt | Smaller — v2 prompt names terminal text after `record_outcomes` as the exit and tells the agent not to keep calling tools past that point |
| Token / context growth | Linear with workflow phases | Smaller for most capabilities, but `propose_review_queue`'s per-item-reasoning output is now the highest-variance source (grows with N queue items) |

The two gaps below are still real and still need explicit decisions, but the urgency is *measured* now rather than *open-ended*. Catastrophic-failure protections (D-019 tool allowlist, HITL gate, single-tenant scope) are unchanged.

---

## What this covers

Two basics, in the colloquial sense:

1. **No infinite loops** — the agent must not be able to spin forever
2. **No unbounded spend** — the agent must not be able to burn arbitrary tokens (= money) on a single run

Both are real gaps. Neither is in any current plan or step task list.

---

## What's already covered (so reader can scope the worry)

Worth naming explicitly so this doc is not mistaken for "we have no safety at all":

- **Tool allowlist** — D-019 enforces that the agent's surface is domain wrappers only. It cannot invoke arbitrary MongoDB. The `test_agent_does_not_expose_mcp_directly` test on `main` guards this.
- **HITL gate** — `LongRunningFunctionTool` at the `request_human_approval` capability means nothing publishes to Shopify / Printful / social without a human `FunctionResponse`. Structurally prevents "agent goes rogue and ships bad campaigns" regardless of loop behavior.
- **Precondition enforcement (new with D-021)** — every capability wrapper raises `PreconditionError` with self-correcting messages if called before its data dependencies are met. The agent cannot enter a "calling random tools in random order" spin — it gets pointed at the right next call within one round-trip. This eliminates a class of failure modes that pre-D-021 worried about.
- **Single-tenant, batch-bounded** — one operator, one batch per event. Blast radius of a runaway is one event's worth of LLM calls, not a fleet's worth.
- **Trace evals** — per-capability pass-rate measurement gives behavioral signal before production.

These cover the *catastrophic* failure modes. The two below cover the *operational* failure modes.

---

## Gap 1 — Loop iteration bound

**State today:** ADK has a default max-iterations cap. We have not chosen a value or written it down.

**Concrete failure mode:** the `edit_requested → draft_campaigns_for_queue` loop-back at `request_human_approval` has no framework-level revision cap. **Partially mitigated:** `prompts/v2/agent_system.md` instructs the agent to stop redrafting after 3 cycles and surface a recommendation to escalate. That prompt-level rule is the demo-day safety net but is not enforced — a model that ignores the rule still spins until ADK's default iteration cap fires (whatever value that is).

**Followup actions:**
- Pick an ADK iteration cap value explicitly; document in `agentic-model.md`
- The prompt-level revision cap is in place (`prompts/v2/agent_system.md`); consider adding a hard tool-level cap inside `request_human_approval` for defense-in-depth before that capability ships

**Priority:** medium overall. The demo-visible failure mode is partially defended by the v2 prompt's 3-cycle rule; **high before `request_human_approval` ships** if we want defense-in-depth via a tool-level cap rather than relying on the prompt alone.

**Resolution (Step 7 / D-031) — CLOSED.** All three layers land with `request_human_approval` (the capability that triggers the loop):
1. **Tool-level hard cap** — `redraft_campaigns` increments `tool_context.state["redraft_cycles"]` and **refuses** past `MAX_REDRAFT_CYCLES` (env, default **3**), returning an "escalate to operator" result instead of redrafting. Robust to LLM mis-ordering because it counts *actual* invocations, not prompt compliance. The cap counter is asserted to survive the HITL suspend/resume park (Tier-1 eval).
2. **Prompt-level rule** — the 3-cycle escalation rule is ported from `prompts/v2/agent_system.md` into `prompts/v3/coordinator_system.md` (v3 has no `agent_system.md`).
3. **ADK iteration cap (framework backstop)** — set explicitly to **30** on the coordinator runner: comfortable headroom over the worst-case *legitimate* turn count (dispatch + apply + 3 redraft cycles + execute + terminal ≈ 12–15). The load-bearing bound is the redraft cap (3); 30 is the catch-all backstop. Recorded in `CLAUDE.md` § ADK-Specific Rules.

---

## Gap 2 — Token / spend bound

**State today:** no `max_output_tokens` on the model, no cost ceiling per run, no context-growth management across the 8 phases.

**Concrete failure mode:** the macro flow touches a lot of tool I/O. A full run on a 50-image batch routes through 9 capabilities of LLM reasoning + wrapper responses; conversation history grows unmanaged. `propose_review_queue` is the highest-variance capability — its output is per-item reasoning for N queued items, which scales with batch size. Plausibly blows context window or burns more tokens than expected on a larger batch.

**Followup actions:**
- Set a per-call `max_output_tokens` (cheap; one config line). **Step 5 is where this lands for the strategic node** — `build_review_queue_node` sets `generate_content_config` with an explicit `max_output_tokens` bounded for the queue payload (it scales with N surfaced items). Tracked as a Step 5 task (D-029). **Step 6** continues the pattern: `_draft_copy_for_asset` sets `max_output_tokens` on the copy call, sized for one item's headline+caption+hashtags — bounded *per item* (the node iterates per-asset), so it does not scale within a single call (D-030).
- **Measure** token usage during Step 1 trace evals — not as a guardrail, as a baseline. If one capability is already 30k tokens, we want to know before `execute_approved_campaigns`, not after. Pay particular attention to `propose_review_queue` once it lands — its per-item-reasoning output is the most likely to grow unexpectedly with batch size.
- Defer the per-run cost-ceiling plumbing unless measurement says we need it

**Priority:** medium. The `max_output_tokens` setting is cheap to add now. The measurement pass should ride along with the Step 1 eval work that's already on the branch. Cost-ceiling plumbing can wait.

---

## Out of scope here

These are real concerns for a production version, not load-bearing for the hackathon demo:

- Per-tool retry / circuit-breaker for Shopify / Printful 5xx — `execute_approved_campaigns` concern, handled at the wrapper layer when that capability is built
- Per-call timeouts (other than Printful poll, which is internal to `execute_approved_campaigns`)
- Semantic output filtering / PII scrubbing — not relevant to the demo workload
- Multi-tenant rate limits — not a single-tenant demo concern

---

## Cross-references

- `docs/agentic-model.md` — establishes the loop shape these measures bound
- `docs/evaluation-strategy.md` — behavioral measurement (orthogonal to the operational bounds above)
- `CLAUDE.md` § ADK-Specific Rules — where the iteration cap value should be recorded once chosen
