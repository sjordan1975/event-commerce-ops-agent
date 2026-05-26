# Evaluation Strategy

Draft. Evals are a first-class engineering concern, not a hackathon afterthought. This document defines what we evaluate, how we detect failure, how we diagnose it, and how we remediate.

> Evaluation is arguably the hardest part of building an agentic system. The system is non-deterministic, the failure modes are subtle, and the cost of "it worked when I tried it once" thinking is a demo that fails on stage. Treat evals like tests: write them before or alongside the implementation; run them in CI; investigate every failure.

---

## Why this matters more for agentic systems than for ordinary code

Ordinary code: given fixed input, fails the same way every time. A unit test catches it.

Agentic code: given fixed input, may pass 9 runs and fail the 10th. Or pass on `gemini-2.5-flash-lite` and fail on `gemini-2.5-flash`. Or pass when the prompt has 4 tools and fail when it has 5. The failures are statistical and the surface area is the entire LLM + prompt + tool-surface co-design.

The implication: passing a smoke test once is not evidence the system works. We need to know the failure rate, and we need traces when failures happen so we can iterate the prompt, the tool docstrings, or the tool surface itself — not just shrug and re-run.

---

## What we evaluate

Five failure categories. Each has its own detection mechanism.

### 1. Tool-selection failure
Agent fails to call a tool it should have called, or calls a tool that wasn't appropriate.

*Example:* Step 1 prompt says "ingest this event" — agent calls `record_event` without ever calling `compute_timeliness`. Or skips `record_assets` entirely.

*Detection:* trace assertion — required tool calls appear by name.

### 2. Tool-sequencing failure
Agent calls the right tools but in the wrong order.

*Example:* Step 1 — agent calls `record_event` before `compute_timeliness`, then has to retry once the Pydantic validation fails. (Self-correcting, but the recovery noise pollutes the trace.)

*Detection:* trace assertion — tool call ordering matches required precedence.

### 3. Tool-argument failure
Agent calls the right tool in the right order but with wrong arguments.

*Example:* Step 1 — agent calls `compute_timeliness(outcome_type="upset_victory", kickoff_utc="07:00:00")` using local time instead of UTC. Output looks plausible (a number in [0,1]) but is wrong.

*Detection:* trace assertion on tool args against expected/derived values. The hardest category to write generic tests for.

### 4. Tool-output handling failure
Agent calls the right tool, gets the right output, then ignores it.

*Example:* Step 1 — agent calls `compute_timeliness`, gets back `{"timeliness": 0.94}`, then calls `record_event` with `timeliness=0.85` (hallucinated). The chain ran but the value didn't propagate.

*Detection:* trace assertion that compares tool outputs to downstream tool inputs. This is the case D-019 specifically named for the timeliness chain.

### 5. End-state failure
All tools called correctly, but the resulting MongoDB state is wrong.

*Example:* `record_assets` is called twice instead of once with all images. Or `event_id` foreign key in `assets` doesn't match the `events.event_id` actually written.

*Detection:* post-condition assertion against MongoDB after the run completes.

---

## How we detect — the three eval surfaces

### A. Trace-based unit evals (per step, fast, mocked DB)

The primary surface. One eval file per workflow step under `tests/evals/`. Each test:

1. Mocks the McpToolset client so MongoDB operations are captured, not executed.
2. Drives the agent via `Runner.run_async` with an operator-realistic input.
3. Collects the event stream.
4. Asserts on the tool-call sequence, args, and output-to-input chains.
5. On failure, dumps the full trace (tool calls + reasoning text + LLM responses) to stderr and to a file under `tests/evals/_failures/`.

Pattern:

```python
async def test_step_1_compute_timeliness_chains_into_record_event():
    runner, captured = await build_runner_with_mock_db()
    prompt = "We just finished Argentina vs France 3-2. Photos in /tmp/wc-final/. ..."

    events = [e async for e in runner.run_async(user_id="t", session_id="s", new_message=prompt)]
    calls = extract_tool_calls(events)

    # (1) selection
    assert any(c.name == "compute_timeliness" for c in calls), dump_trace(events)
    assert any(c.name == "record_event"       for c in calls), dump_trace(events)

    # (2) sequencing
    assert idx(calls, "compute_timeliness") < idx(calls, "record_event"), dump_trace(events)

    # (4) output handling — no hallucination
    timeliness_out = output_of(calls, "compute_timeliness")["timeliness"]
    record_event_in = args_of(calls, "record_event")["event"]["timeliness"]
    assert timeliness_out == record_event_in, dump_trace(events)
```

These run on every PR. Fast (no live DB), deterministic on the test side, with the only nondeterminism being the LLM itself.

### B. Trace-based integration evals (cross-step, slower, real DB)

Per-step evals miss cross-step issues — wrong `event_id` foreign keys, queue assignments that don't match what the next step expects, etc. A small set of integration evals walks the agent through multi-step sequences against a real Atlas dev cluster, asserting both trace shape and MongoDB end-state.

Run on merge to `main`, not on every PR. One golden trace per major flow: ingestion → context → routing → scoring → drafting → approval → execution.

### C. Statistical / repetition evals (failure rate)

Smoke tests pass once. The question we actually care about is: **across 20 runs of this input, how often does the agent get it right?**

For each step, the trace eval is run N times (configurable; default 5 in CI, 20 manually). The result is a pass rate, not a binary. A test that passes 5/5 in CI but 18/20 manually is a flake we should be nervous about.

Threshold for shipping: each step's tool-sequencing eval must pass ≥ 95% across 20 runs. Below that → the system prompt or tool surface needs work; do not ship.

This is where the timeliness fallback gets triggered (D-019 Open Q #6 resolution): if the timeliness chain passes < 90% across runs, switch to the hybrid wrapper that computes internally as defense.

---

## Diagnosis — what a failure trace must contain

When an eval fails, the dumped trace must be sufficient to answer:

1. **What did the agent decide to do?** Full LLM reasoning text per turn — not just tool calls.
2. **Which tools did it call, in what order, with what args, and what did each return?**
3. **What did the system prompt look like at the time of the run?** (Pin the prompt version.)
4. **What was the input prompt?**
5. **What model was used?** (`GEMINI_MODEL` env var at run time.)

A failure is one of:
- **Prompt issue** — system prompt doesn't describe the chain clearly enough
- **Docstring issue** — tool docstring doesn't convey when to call it
- **Surface issue** — tool surface is ambiguous (two tools that look similar)
- **Model capability issue** — the model can't do this reliably even with a clear prompt
- **Real bug** — wrapper or model code is broken

Diagnosis is the work of reading the trace and deciding which it is. The remediation differs for each.

**Discipline note:** when a trace surfaces a partial result, do not declare "acceptable" or "acceptable for MVP" until the cheapest remediation rung has been tried. The playbook table below is a checklist to run top-to-bottom, not a reference to consult after the fact.

---

## Remediation playbook

| Failure cause | Remediation in order of cost |
|---|---|
| Prompt issue | (1) tighten system prompt language about the chain; (2) add a worked example to the prompt; (3) add a few-shot example showing the right call sequence |
| Docstring issue | Tighten the tool docstring — be explicit about preconditions and when to call |
| Surface issue | Rename a tool to disambiguate; merge or split tools; remove tools the agent shouldn't be calling at all |
| Model capability issue | (1) try a more capable model; (2) consider a hybrid wrapper that defends against the failure (D-019 Q#6 pattern); (3) restructure the workflow to remove the inference the model can't do |
| Real bug | Fix the code |

Always start with the lowest-cost remediation and re-run the eval at the failure rate threshold before moving up the ladder.

---

## What gets evaluated in each step

| Step | Required tool calls (sequenced) | Output-to-input chains | End-state assertions |
|---|---|---|---|
| 1 — Ingestion | `compute_timeliness` → `record_event` → `record_assets` | `compute_timeliness.output.timeliness` == `record_event.args.event.timeliness` | `events` has 1 doc with right outcome; `assets` has N docs with `event_id` matching |
| 2 — Context | `get_event` → `get_past_events_by_outcome` → `get_performance_baseline_by_outcome` → `get_player_context_for_teams` → `save_event_narrative` | event_id from `get_event` flows into `save_event_narrative` | `events` has narrative field populated |
| 3 — Vector search | per asset: `compute_image_embedding` → `find_similar_assets` → `save_asset_embedding` + `save_similar_assets` | embedding output flows into both find and save | every asset has embedding + similar_assets |
| 4 — Scoring | per asset: `score_asset_with_vision` → `save_asset_scores` → `assign_asset_to_queue` | scores output flows into save | every asset has scores, queue_type, product_route |
| 5 — Draft | `get_event` + `get_assets_for_event` → per asset: `submit_campaign_for_review` | event narrative read flows into campaign copy | `campaigns` count matches; `approvals` queue populated |
| 6 — HITL | `await_human_approval` → `record_approval_decision` (on resume) | approval_id flows through | asset status reflects decision |
| 7 — Execution | `mark_asset_executing` → external calls → `record_execution_result` (or `_failure`) | campaign_id flows through | asset status = published; published_urls populated |
| 8 — Feedback | `record_performance` | n/a | `performance` has docs for each published asset |

This table is the evaluation contract. Every step's implementation must be accompanied by the trace eval that asserts it.

---

## What we are *not* doing (MVP scope)

These are real eval practices that are out of scope for the hackathon. Naming them so we don't pretend to have them:

- **LLM-as-judge** for narrative quality / copy quality. Step 5 generates campaign copy; we don't auto-grade it. Human review on the demo path is the only quality gate.
- **Behavioral diffs across model versions.** If we change `GEMINI_MODEL`, we re-run all evals manually; we don't have an automated cross-model comparison.
- **Statistical significance testing.** Pass rate ≥ 95% across 20 runs is a heuristic, not a confidence interval.
- **Adversarial / red-team prompts.** We don't probe for prompt-injection robustness. The agent is operator-facing in this demo, not adversarial-user-facing.
- **Continuous eval against production traffic.** No production traffic exists.
- **Cost / token-usage budgets per step.** Worth measuring eventually; not gating MVP.

The MVP eval surface is intentionally a sharp wedge: trace-based assertions per step, integration evals across the workflow, repetition for failure rate. That's enough to ship a demo that doesn't break on stage.

---

## Test layout

```text
tests/
  evals/
    __init__.py
    _failures/                  ← dumped traces from failed runs (gitignored)
    conftest.py                 ← build_runner_with_mock_db, extract_tool_calls helpers
    test_step_1_trace.py        ← unit evals for Step 1
    test_step_2_trace.py
    ...
    test_workflow_integration.py ← integration evals across steps
    test_failure_rate.py         ← repetition runner; not part of standard CI run
```

`tests/evals/` is the eval surface. `tests/test_*.py` (outside `evals/`) remains for ordinary unit tests (Pydantic validation, pure functions, etc).

---

## Open questions

1. **How do we capture LLM reasoning text from the ADK event stream?** Resolved by `spike/adk_event_capture.py` (2026-05-25). Each `event.content.parts` entry is a `types.Part` with one of `text` / `function_call` / `function_response` populated. Args and responses are inspectable as Python dicts — no string parsing. Chain assertions (output-of-tool-A flows into args-of-tool-B) are directly implementable.

   *Reasoning text findings (three configurations tested):*
   - **Baseline** (`gemini-2.5-flash-lite`, minimal prompt): 0 intermediate text parts. Model goes straight tool_call → tool_response → final answer.
   - **CoT-prompted** (`gemini-2.5-flash-lite` + "Before each tool call, state in one sentence why you are calling it"): 2 intermediate text parts captured *before* each tool call, plus the final response. Example output: *"I will first add 12 and 30 to find their sum."* before the `add` call; *"I will then multiply the result of the addition (42) by 5 to find the final product."* before the `multiply` call.
   - **CoT + larger model** (`gemini-2.5-flash` + same CoT prompt): equivalent to flash-lite + CoT. No measurable advantage.

   *Conclusion:* CoT prompting on `gemini-2.5-flash-lite` is sufficient — the cheaper mitigation wins. We do **not** need to switch models. The eval-mode system prompt (and possibly the production system prompt) should include the line: *"Before each tool call, briefly state in one sentence why you are calling it and what you expect to learn."* This becomes a load-bearing piece of the failure-diagnosis surface, not just stylistic.
2. **What's the cost of N=20 repetition?** Each Step 1 run is small (a few thousand tokens). Across 8 steps × 20 runs we're at order-of $1-2 per full eval pass. Acceptable. Confirm before committing.
3. **Where do failure traces go in CI?** Local file under `tests/evals/_failures/` is enough for local dev. For CI we'd want them attached to the run artifacts. Defer until CI is set up.
4. **Mocking the McpToolset client** — what's the cleanest seam? Likely `_mcp_toolset()` in `src/agent.py`. May need a small refactor to make it injectable.
