# Step Development Workflow

This project builds one capability per step, end-to-end, before moving to the next. Each step follows the same sequence. No phase is skipped; each has a human review gate before the next begins.

---

## Phase sequence

### 1. Close the previous step

- All verification checkpoints in the step's task file pass
- Commit any open changes on the step branch
- Merge to `main` (fast-forward only — `main` is always green)
- Update `CLAUDE.md` § Current Phase ("Next action" line) to reflect the new state

### 2. Cut the next step branch

```bash
git checkout main
git checkout -b step/{N}-{name}
```

### 3. Write the plan (`docs/plans/step-N-{name}.md`)

One document covering:

- What the capability delivers (agent-facing contract + internal orchestration)
- The capability surface — which tools are agent-facing vs. internal (D-019 + D-021)
- What the LLM does in this capability (bounded vs. judgment-shaped reasoning)
- What the capability does internally (internal call sequence, Pydantic models, DB ops)
- Component table (file → purpose)
- Dependency order (what must exist before what)
- Tool docstring (load-bearing — the agent reads it at tool-call time)
- System prompt context (any prompt changes this step requires)
- Risks and mitigations
- Verification checkpoints (commands + pass criteria)
- Output consumed by (what downstream capability reads this step's output)

**→ Consult advisor, then human review gate.** Advisor sees the full plan in context and catches the misses that compound expensively if carried into tasks/implementation — spec-ordering bugs, under-typed contracts, missing assertions, novelty traps. Revise against advisor feedback before the human gate. Discuss, validate, revise before moving on.

### 4. Write the task list (`docs/tasks/step-N-tasks.md`)

Atomic, numbered tasks (T-N.1, T-N.2, …) derived from the plan. Each task names the file, the change, and any test that validates it. Tasks are the implementation contract — implementation should not deviate from them without updating the task file first.

**→ Human review gate.** Discuss, validate, revise before moving on. Advisor consultation is recommended (not required) when the plan→tasks translation involves judgment calls — batching vs. splitting wrappers, where test coverage breaks naturally, surprising dependency orderings. Skip the advisor call when tasks are mechanically derived and obvious.

### 5. Implement

Work through tasks in dependency order. Run verification checkpoints after each logical group (models → errors → wrappers → capability → evals). Fix root causes; never rewrite tests to make them pass.

**→ Human review gate.** Review implementation, discuss any deviations from plan/tasks.

### 6. Commit and merge

- All verification checkpoints pass (unit tests + trace eval pass-rate gate ≥ 95% / 20 runs)
- **Consult advisor before declaring done** — independent read on whether the implementation matches the plan, whether evals exercise what they claim to, and whether anything was quietly cut to make tests pass. Make the deliverable durable first (commit before calling) so the result persists if the session ends mid-call.
- Commit on the step branch
- Merge to `main`
- Return to Phase 1

During implementation, advisor self-invocation guidance still applies — call when stuck (errors recurring, approach not converging), when considering a change of approach, or when about to commit to a non-obvious interpretation. No additional formal gate.

---

## What each gate is for

| Gate | What advisor catches | What human review catches |
| --- | --- | --- |
| After plan | Spec-ordering bugs, under-typed contracts, missing assertions, novelty traps, model-default discipline | Spec gaps, implicit assumptions, missing downstream consumers, wrong abstraction level, alignment with product intent |
| After tasks (advisor optional) | Coverage holes when plan→tasks translation involves judgment | Tasks that don't cover the plan, tasks too coarse or too fine, missing test coverage |
| Before declaring done (advisor) + after implementation (human) | Quiet test-rewrites, eval claims that don't match what evals do, plan→code drift | Deviations from plan/tasks, regressions, eval flakiness, docstring mismatches |

The plan → tasks → implementation sequence is not bureaucratic overhead. Step 1's operator interaction model assumption (the agent extracts structured metadata from natural language chat) was implicit in every prior doc and only surfaced during the plan-review gate. Step 2's spec-ordering bug (D-016 spec departure landing as "follow-up after merge" instead of "branch housekeeping before implementation") surfaced during the advisor call on the plan. That kind of miss is cheap to fix in a plan and expensive to fix after implementation.

Advisor calls are *consultations*, not approvals — the call surfaces issues; revision and the human gate decide what to do with them.

---

## Artifacts per step

| Artifact | Lives at | Purpose |
| --- | --- | --- |
| Plan | `docs/plans/step-N-{name}.md` | Design authority — what and why |
| Tasks | `docs/tasks/step-N-tasks.md` | Implementation contract — how, atomically |
| Implementation | `src/`, `tests/` | The thing itself |
| Trace eval | `tests/evals/test_step_N_trace.py` | Pass-rate gate (D-020) |
