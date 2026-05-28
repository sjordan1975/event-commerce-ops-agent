# Evaluation Strategy

> **Updated for D-021** (2026-05-26) — adds a sixth failure category (*strategy coherence*) for queue-assembly assertions; refreshes examples to reflect the 9-capability surface; resolves the timeliness-fallback concern (now moot — `compute_timeliness` is internal to `ingest_event_batch`, no hallucination surface for the agent); resolves the McpToolset mocking open question (Step 0.5 introduced `MongoMCPClient`; mock via `src.db.get_client`). Pair with `docs/agentic-model.md` for the three-layer framing (framework / composition / strategy) that this doc's failure categories map onto.

Draft. Evals are a first-class engineering concern, not a hackathon afterthought. This document defines what we evaluate, how we detect failure, how we diagnose it, and how we remediate.

> Evaluation is arguably the hardest part of building an agentic system. The system is non-deterministic, the failure modes are subtle, and the cost of "it worked when I tried it once" thinking is a demo that fails on stage. Treat evals like tests: write them before or alongside the implementation; run them in CI; investigate every failure.

---

## Why this matters more for agentic systems than for ordinary code

Ordinary code: given fixed input, fails the same way every time. A unit test catches it.

Agentic code: given fixed input, may pass 9 runs and fail the 10th. Or pass on `gemini-2.5-flash-lite` and fail on `gemini-2.5-flash`. Or pass when the prompt has 4 tools and fail when it has 5. The failures are statistical and the surface area is the entire LLM + prompt + tool-surface co-design.

The implication: passing a smoke test once is not evidence the system works. We need to know the failure rate, and we need traces when failures happen so we can iterate the prompt, the tool docstrings, or the tool surface itself — not just shrug and re-run.

---

## What we evaluate

Six failure categories. Each has its own detection mechanism. The first five are capability-level (layer 2 in `agentic-model.md`'s framing); the sixth is strategic (layer 3 — load-bearing for queue-assembly evals per D-021).

### 1. Tool-selection failure
Agent fails to call a capability it should have called, or calls one that wasn't appropriate.

*Example:* Operator prompt says "ingest this event and propose a queue" — agent calls `ingest_event_batch` but never calls `find_similar_assets` or `score_assets_with_vision` before attempting `propose_review_queue` (would be caught by `PreconditionError`, but trace shows the planning gap).

*Detection:* trace assertion — required capability calls appear by name.

### 2. Tool-sequencing failure
Agent calls the right capabilities in an order that violates a data dependency. Note: per D-021's enforced-vs-emergent split, most capability ordering is the agent's choice (the three middle capabilities `build_event_context`, `find_similar_assets`, `score_assets_with_vision` are independent). The sequencing assertion class is weaker than pre-reframe — only the cross-precondition boundaries matter (e.g., `propose_review_queue` must follow all three; `draft_campaigns_for_queue` must follow `propose_review_queue`).

*Example:* Agent calls `draft_campaigns_for_queue` before `propose_review_queue` — wrapper raises `PreconditionError` with self-correcting message; agent recovers but the recovery noise pollutes the trace.

*Detection:* trace assertion — cross-precondition boundaries respected; `PreconditionError` recoveries counted (zero is the target).

### 3. Tool-argument failure
Agent calls the right capability in the right order but with wrong arguments.

*Example:* Agent calls `ingest_event_batch` with `event_metadata={..., "kickoff_utc": "19:00:00"}` (no date, no timezone) instead of the full ISO 8601 string. Wrapper validates and rejects; agent recovers. Or worse: extracts the wrong outcome_type from the operator's natural-language input (e.g., calls a 1-1 draw an `upset_victory`).

*Detection:* trace assertion on capability args against expected/derived values. The hardest category to write generic tests for — natural-language field extraction is judgment-shaped.

### 4. Tool-output handling failure
Agent calls the right capability, gets the right output, then ignores it on a downstream call.

*Example:* Agent calls `propose_review_queue` and gets back a queue with 5 exploitation items + 3 exploration items, then calls `draft_campaigns_for_queue` with only the exploitation items (drops the exploration half on the floor).

*Detection:* trace assertion that compares capability outputs to downstream capability inputs. *(Pre-D-021 this category named the `compute_timeliness → record_event` hallucination case. That case is now moot — `compute_timeliness` is internal to `ingest_event_batch`; the agent never sees the value, so cannot hallucinate it. D-019 Open Q #6's hybrid-wrapper fallback is no longer needed for this chain.)*

### 5. End-state failure
All capabilities called correctly, but the resulting MongoDB state is wrong.

*Example:* `ingest_event_batch` is called twice instead of once with all images. Or `event_id` foreign key in `assets` doesn't match the `events.event_id` actually written. Or `record_outcomes` writes performance docs with the wrong `campaign_id`.

*Detection:* post-condition assertion against MongoDB after the run completes.

### 6. Strategy-coherence failure *(new — per D-021)*
Agent calls `propose_review_queue` correctly (right preconditions met, capability returns a queue) but the queue's **composition** does not match what the event class warrants, or per-item reasoning is missing, generic, or ungrounded.

*Example:* For an `upset_victory` event with peak timeliness, agent surfaces 2 items total (queue too thin); or surfaces 20 items with identical *"this image is worth surfacing"* boilerplate reasoning (per-item reasoning is generic, not earning its keep); or surfaces an exploration pick whose rationale ignores the event narrative entirely (*"this is a sharp photo"* — true but useless).

*Detection:* assertions on `propose_review_queue`'s output, plus assertions across event-class comparisons:
- Exploitation count + exploration count are within expected bounds for the event class (`upset_victory` → rich exploitation; `draw` → thin exploitation, exploration emphasis).
- Every surfaced item has per-item reasoning with non-trivial length and event-narrative grounding.
- For two events of different `outcome_type`, the queue composition differs visibly (the demo's two-event contrast — see `strategic-agent-reframe.md` § Demo coherence).

This is the load-bearing new category. It is also **the hardest to write deterministic assertions for** — the assertions are statistical and soft, not binary. A queue with "4 exploitation items, 3 exploration items, with grounded reasoning" is not the only acceptable answer; "5/2" or "3/4" might be equally good. The remediation playbook still applies (prompt → docstring → surface → hybrid → model) but the "right answer" surface is fuzzier than for capability-level failures. Expect to spend more eval-writing effort here than on categories 1–5.

*Specific to queue assembly because:* categories 1–5 cover capability-level concerns (did the right capability fire correctly). Strategy coherence is about the **output quality of the one strategic capability** — the agent might call `propose_review_queue` correctly and still produce a bad queue. Different failure mode, different remediation lens.

---

## How we detect — the three eval surfaces

### A. Trace-based unit evals (per step, fast, mocked DB)

The primary surface. One eval file per capability (typically named alongside the implementation step that introduces it — e.g., `test_step_1_trace.py` covers `ingest_event_batch`) under `tests/evals/`. Each test:

1. Mocks `MongoMCPClient` (via `src.db.get_client`) so MongoDB operations are captured, not executed.
2. Drives the agent via `Runner.run_async` with an operator-realistic input.
3. Collects the event stream.
4. Asserts on the capability calls, args, outcomes (and, for `propose_review_queue`, strategy coherence).
5. On failure, dumps the full trace (tool calls + reasoning text + LLM responses) to stderr and to a file under `tests/evals/_failures/`.

Pattern (Step 1, capability-level — covers categories 1, 3, 5):

```python
async def test_ingest_event_batch_writes_correct_event_and_assets():
    runner, mock_client = await build_runner_with_mock_db()
    prompt = (
        "We just finished Argentina vs France 3-2. Photos in /tmp/wc-final/. "
        "Match started 19:00 UTC, finished ~20 min ago. Get them into the system."
    )

    events = [e async for e in runner.run_async(user_id="t", session_id="s", new_message=prompt)]
    calls = extract_tool_calls(events)

    # (1) selection — agent called the one Step 1 capability
    assert any(c.name == "ingest_event_batch" for c in calls), dump_trace(events)
    assert len([c for c in calls if c.name == "ingest_event_batch"]) == 1, dump_trace(events)

    # (3) arguments — agent extracted event metadata correctly from natural language
    args = args_of(calls, "ingest_event_batch")
    meta = args["event_metadata"]
    assert meta["home_team"] == "Argentina"
    assert meta["away_team"] == "France"
    assert meta["outcome_type"] == "upset_victory"
    assert meta["start_date"].startswith("2026-")  # ISO 8601, UTC

    # (5) outcome — MongoDB state after capability returned
    inserts = [c for c in mock_client.calls if c.tool == "insert-many"]
    event_inserts  = [i for i in inserts if i.args["collection"] == "events"]
    asset_inserts  = [i for i in inserts if i.args["collection"] == "assets"]
    assert len(event_inserts) == 1
    assert event_inserts[0].args["documents"][0]["timeliness"]  # computed internally — non-null
    assert len(asset_inserts[0].args["documents"]) == 47  # all images written in one batch

    # CoT reasoning text is present (load-bearing for diagnosis)
    assert any(part.text for event in events for part in event.content.parts)
```

For `propose_review_queue` the assertion shape grows to include category 6 (strategy coherence) — see § What gets evaluated below.

These run on every PR. Fast (no live DB), deterministic on the test side, with the only nondeterminism being the LLM itself.

### B. Trace-based integration evals (cross-step, slower, real DB)

Per-step evals miss cross-step issues — wrong `event_id` foreign keys, queue assignments that don't match what the next step expects, etc. A small set of integration evals walks the agent through multi-step sequences against a real Atlas dev cluster, asserting both trace shape and MongoDB end-state.

Run on merge to `main`, not on every PR. One golden trace per major flow: ingestion → context → routing → scoring → drafting → approval → execution.

### C. Statistical / repetition evals (failure rate)

Smoke tests pass once. The question we actually care about is: **across 20 runs of this input, how often does the agent get it right?**

For each step, the trace eval is run N times (configurable; default 5 in CI, 20 manually). The result is a pass rate, not a binary. A test that passes 5/5 in CI but 18/20 manually is a flake we should be nervous about.

Threshold for shipping: each capability's trace eval must pass ≥ 95% across 20 runs. Below that → the system prompt, tool docstring, or capability surface needs work per the remediation playbook; do not ship.

**Strategy-coherence (category 6) has a softer threshold by nature.** Since "the right queue" is a range, not a point, the assertion class is "queue meets event-class expectations" (e.g., upset_victory produces ≥3 exploitation items + ≥1 exploration item, all with grounded per-item reasoning) rather than "queue equals this exact composition." The 95% pass-rate target still applies, but the assertion writing is fuzzier — expect to iterate the expectation bands as we observe the agent's actual behavior on demo events. See `strategic-agent-reframe.md` § Demo coherence for the two demo events (upset victory + group-stage draw) that anchor the strategy-coherence eval set.

*(Pre-D-021 this section also described a timeliness-fallback hybrid wrapper triggered by < 90% pass rate on the `compute_timeliness → record_event` chain. That concern is moot post-D-021 — `compute_timeliness` is internal to `ingest_event_batch`, so the agent has no opportunity to hallucinate the value. D-019 Open Q #6's fallback was retired with the reframe.)*

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
| --- | --- |
| Prompt issue | (1) tighten system prompt language about the chain; (2) add a worked example to the prompt; (3) add a few-shot example showing the right call sequence |
| Docstring issue | Tighten the tool docstring — be explicit about preconditions and when to call |
| Surface issue | Rename a tool to disambiguate; merge or split tools; remove tools the agent shouldn't be calling at all |
| Model capability issue | (1) try a more capable model; (2) consider a hybrid wrapper that defends against the failure (D-019 Q#6 pattern, though that specific case is no longer live post-D-021); (3) restructure the workflow to remove the inference the model can't do |
| Real bug | Fix the code |
| **Strategy-coherence issue** *(category 6)* | (1) tighten the `propose_review_queue` docstring to convey what "good queue composition" looks like for each event class; (2) sharpen the system prompt's per-item-reasoning expectations (specificity, narrative grounding); (3) widen the assertion bands if observed behavior is consistently outside the expected range but qualitatively reasonable — the eval may be wrong, not the agent; (4) restructure the capability's output schema to force structure (e.g., require explicit `narrative_fit_score` per item); (5) escalate to a more capable model only after the above |

Always start with the lowest-cost remediation and re-run the eval at the failure rate threshold before moving up the ladder. **Strategy-coherence failures specifically: be willing to question the eval's expectation bands first.** Unlike categories 1–5 where the right answer is unambiguous, here the agent might be producing a defensible queue that the eval simply doesn't recognize as good. Read the trace and the per-item reasoning before assuming the agent is wrong.

---

## What gets evaluated in each capability

| Capability | Capability call(s) | Outcome assertions | Strategy assertions |
| --- | --- | --- | --- |
| `ingest_event_batch` | one call with extracted `event_metadata` + image list | `events` has 1 doc with right `outcome_type` and computed `timeliness`; `assets` has N docs with matching `event_id`, `status="ingested"` | — |
| `build_event_context` | one call with `event_id` | event narrative present in agent state with structured fields (`narrative_angle`, `key_figures` with grounded facts from `player_context`, `commercial_timing`, `historical_baseline`); `player_context.find` was invoked | — |
| `find_similar_assets` | one call with `event_id` | every asset has `embedding` populated; `similar_assets` populated for assets that had matches; mock recorded `vectorSearch` call | — |
| `score_assets_with_vision` | one call with `event_id`; preconditions: ingested assets exist | every asset has 5-dimensional `scores`; Vision API call count matches asset count | — |
| **`propose_review_queue`** | one call with `event_id`; preconditions: event + assets + similarity + scores + narrative all present | every asset has `queue_type` (`exploitation` / `discovery` / `null`); per-item reasoning attached to each queued item | **Load-bearing — see Strategy coherence (category 6).** For upset_victory: exploitation count ≥ 3, exploration count ≥ 1, all per-item reasoning grounded in narrative. For draw: exploitation count thin (may be 0–2), exploration count ≥ 2 with non-generic rationale. Cross-event-class: queue composition differs visibly between event types. |
| `draft_campaigns_for_queue` | one call with queue items; preconditions: queue proposed | `campaigns` count matches queued items; `approvals` queue populated with `status="pending"`; copy fields reference event narrative substrate | — |
| `request_human_approval` | one call; suspends; resumes with decision batch | approval statuses updated per decisions; asset statuses synced; on `edit_requested`, redraft cycle bounded to ≤ 3 rounds per safety-measures.md | — |
| `execute_approved_campaigns` | one call with approved items; preconditions: approvals with `status="approved"` exist | approved assets have `status="published"`; `published_urls` populated per `product_route`; mock recorded Shopify + Printful + social-queue operations | — |
| `record_outcomes` | one call with executed campaigns | `performance` has docs for each published asset with channel-appropriate metric shape (per `product_route`) | — |

This table is the evaluation contract. Every capability's implementation must be accompanied by the trace eval that asserts it. The strategy column is only populated for `propose_review_queue` — that is the one capability whose output is judgment-shaped rather than outcome-shaped.

**Cross-event-class evals for `propose_review_queue`:** run two evals back-to-back (upset_victory event + draw event), then assert that the queue compositions differ visibly. A single-event eval cannot catch the failure mode *"the agent produces the same queue shape regardless of event."* This is the eval-level expression of the demo's two-event contrast (`strategic-agent-reframe.md` § Demo coherence).

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
4. ~~Mocking the McpToolset client~~ — **resolved (2026-05-25, Step 0.5).** `MongoMCPClient` in `src/db/client.py` is the seam. Mock via monkeypatching `src.db.get_client` to return a `MagicMock` whose `call()` records invocations. This pattern is reusable across every capability's trace eval — `tests/evals/conftest.py` will expose `build_runner_with_mock_db()` returning `(runner, mock_client)`.
