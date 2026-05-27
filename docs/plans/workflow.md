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

**→ Human review gate.** Discuss, validate, revise before moving on.

### 4. Write the task list (`docs/tasks/step-N-tasks.md`)

Atomic, numbered tasks (T-N.1, T-N.2, …) derived from the plan. Each task names the file, the change, and any test that validates it. Tasks are the implementation contract — implementation should not deviate from them without updating the task file first.

**→ Human review gate.** Discuss, validate, revise before moving on.

### 5. Implement

Work through tasks in dependency order. Run verification checkpoints after each logical group (models → errors → wrappers → capability → evals). Fix root causes; never rewrite tests to make them pass.

**→ Human review gate.** Review implementation, discuss any deviations from plan/tasks.

### 6. Commit and merge

- All verification checkpoints pass (unit tests + trace eval pass-rate gate ≥ 95% / 20 runs)
- Commit on the step branch
- Merge to `main`
- Return to Phase 1

---

## What each gate is for

| Gate | What it catches |
| --- | --- |
| After plan | Spec gaps, implicit assumptions, missing downstream consumers, wrong abstraction level |
| After tasks | Tasks that don't cover the plan, tasks that are too coarse or too fine, missing test coverage |
| After implementation | Deviations from plan/tasks, regressions, eval flakiness, docstring mismatches |

The plan → tasks → implementation sequence is not bureaucratic overhead. Step 1's operator interaction model assumption (the agent extracts structured metadata from natural language chat) was implicit in every prior doc and only surfaced during the plan-review gate. That kind of miss is cheap to fix in a plan and expensive to fix after implementation.

---

## Artifacts per step

| Artifact | Lives at | Purpose |
| --- | --- | --- |
| Plan | `docs/plans/step-N-{name}.md` | Design authority — what and why |
| Tasks | `docs/tasks/step-N-tasks.md` | Implementation contract — how, atomically |
| Implementation | `src/`, `tests/` | The thing itself |
| Trace eval | `tests/evals/test_step_N_trace.py` | Pass-rate gate (D-020) |
