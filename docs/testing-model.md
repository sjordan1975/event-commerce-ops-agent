# Testing Model for an Agentic System

Companion to `evaluation-strategy.md`. The eval-strategy doc covers *how* we test the agent's behavior; this doc covers the *mental model* — what's a unit test, what's an eval, and where the boundary is.

---

## The three categories

| Category | What it is | Test type | Deterministic? |
|---|---|---|---|
| 1. Tool implementations | Python functions (pure or with side effects) | Unit tests, possibly with mocks | Yes |
| 2. Scaffolding | Static text — system prompts, tool docstrings, schemas | Unit tests on file contents / loaded strings | Yes |
| 3. Agent behavior | The LLM's choices about which tools to call, with what args, in what order | **Trace evals** — capture what happened, assert against the trace | No (statistical) |

Categories 1 and 3 are easy to recognize. Category 2 is the easy-to-miss middle ground: testing that `prompts/v1/agent_system.md` loads and contains the CoT directive; testing that every FunctionTool's docstring is non-empty; testing that the Pydantic models validate correctly. All deterministic. All regular unit tests. None involve an LLM.

---

## Where the AI lives — and doesn't

In an agentic system, the LLM is exactly one layer: **deciding what to do next given the prompt, conversation history, and tool descriptions**. It's a function in the mathematical sense (input → output) but it's *probabilistic* — same input may produce different outputs across runs. Below and above it, everything else is regular code.

```text
   USER INPUT
        │
        ▼
   ┌────────────┐
   │  LLM       │  ← probabilistic
   │  reasoning │
   └────────────┘
        │                ▲
   tool call         tool response
        ▼                │
   ┌─────────────────────────┐
   │ Python function (tool)  │  ← deterministic
   │ may call MongoDB, etc.  │
   └─────────────────────────┘
        │
        ▼
   side effect (DB write, etc.)
```

The LLM is the only probabilistic layer. Everything below the agent boundary is regular code. Unit testing the tools tests the lower half exhaustively. Trace evals test what crosses the boundary.

---

## Concrete examples from this project

| Test | What it asserts | Deterministic? | Why |
|---|---|---|---|
| `test_timeliness.py`: 4h after kickoff → base/2 | Math | Yes | Pure function, no external deps |
| `test_models.py`: `Event(outcome_type="bogus")` raises | Validation | Yes | Pydantic, no external deps |
| `test_step_1.py::test_record_event`: wrapper sends correct `insert-many` args | Wrapper plumbing | Yes (client is mocked) | Mock removes the only nondeterminism |
| `test_foundation.py`: system prompt contains CoT directive | Scaffolding | Yes | Static file content |
| `test_foundation.py::test_agent_does_not_expose_mcp_directly` | Tool registration | Yes | Agent's `tools` list is built at construction time, not LLM time |
| `test_step_1_trace.py`: agent calls `compute_timeliness` before `record_event` | Agent decision | **No** | Depends on LLM |
| `test_step_1_trace.py::pass_rate`: ≥19/20 runs succeed | Reliability of agent behavior | **No, statistical** | LLM distribution |

The split is sharp: the first five rows are unit tests in the classical sense. The last two are evals. **Different category, different reliability model, different diagnostic playbook.**

---

## What "tested differently" actually means

For the deterministic tests: passing once = the code is correct. Failure means a bug.

For trace evals: passing once is **not** evidence the system works. Failure could mean:

- The system prompt isn't clear enough
- The tool docstring doesn't convey when to call it
- The tool surface is confusable
- The model isn't capable enough
- An actual bug in a wrapper

The remediation playbook (D-020) orders fixes by cost: prompt → docstring → surface → hybrid wrapper → model swap. *None of these are "fix the bug."* A trace eval failure is closer to a "the user can't figure out the UI" bug than a "the function returns the wrong value" bug.

That's why CLAUDE.md commits to **pass rate ≥ 95% across 20 runs** as the ship gate, not "test passes." A test that passes 18/20 isn't broken — it's unreliable. That's a different problem with different fixes.

---

## The subtle point that matters in practice

A passing unit test on `record_event` means: *the wrapper is correct **when given correct input**.*

It does **not** mean: *the agent will give the wrapper correct input.*

Those are different claims. The second one requires a trace eval.

This sounds obvious but it has a real consequence: in an agentic system, **unit-test coverage doesn't imply behavioral correctness**. You can have 100% unit-test coverage on every wrapper, every model, every pure function, and still have an agent that fails to call them in the right order. Unit tests verify the **building blocks**. Trace evals verify the **agent's assembly of those blocks into behavior**.

In a conventional system, you'd write integration tests to bridge that gap. In an agentic system, trace evals serve the same purpose — but they're statistical rather than binary, and the remediation playbook is different (prompts and docstrings, not code).

---

## How this maps onto the Step 1 task list

Going through the Step 1 task list with this lens:

| Task | Type | Notes |
|---|---|---|
| T-1.1–1.2 (Pydantic models) | Unit | Classical |
| T-1.3 (conftest helpers) | Unit | Classical |
| T-1.4 (timeliness calculator) | Unit | Pure function |
| T-1.5 (lazy `get_client()`) | Unit | Tests `c1 is c2` — singleton behavior |
| T-1.6–1.7 (record_event, record_assets wrappers) | Unit with mock | Mock `get_client` to capture calls |
| T-1.8 (`all_function_tools` registered) | Scaffolding-ish | Asserts the list is shaped correctly |
| T-1.9 (auto-wire) | Scaffolding | Asserts `build_agent()` includes the three names |
| T-1.10 (eval scaffold) | Infrastructure | Helpers for trace evals |
| T-1.11–1.12 (trace evals) | **Eval** | Different category. Probabilistic. |

11 out of 13 tasks are classical unit/scaffolding tests. Only 2 are evals. That ratio is roughly what you'd expect across the whole project — the eval surface is small but the trace evals are the load-bearing tests for "does the agent work?"

---

## The mental model worth carrying forward

- **Tools are functions.** Test them like functions. Mock their external dependencies. Same as any code.
- **Pydantic models are validators.** Test them like validators. Same as any code.
- **Prompts and tool docstrings are configuration.** Test that they load and contain required content. Same as any config.
- **The agent's *behavior* is the thing that's new.** It's tested via traces, statistically, with a different diagnostic playbook. Don't conflate it with the unit-test surface.

The phrase that captures it: **in agentic systems, you unit-test the parts and you eval the whole.**

---

## Cross-references

- `docs/evaluation-strategy.md` — how trace evals actually work (failure categories, eval surfaces, remediation playbook, per-step eval contract)
- `CLAUDE.md` § Evaluation — operational rules (95% pass rate, CoT directive load-bearing, five failure categories)
- `tracking.md` D-020 — the decision to treat evals as first-class
- `spike/adk_event_capture.py` — verified pattern for capturing tool calls / responses / reasoning text from the ADK event stream
