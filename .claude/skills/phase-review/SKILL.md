---
name: phase-review
description: >
  Close a phase of PROJECT-BRIEF.md: run `make check`, run the three phase-exit
  reviewers in parallel (test-reviewer, determinism-auditor, coherence-auditor), merge
  their reports into one acceptance table (criterion, pass/fail, evidence) and a
  must-fix list, then fix and land the phase-exit PR. Use when every PR of a phase has
  merged (autopilot step 1), or when asked whether a phase is done.
---

# phase-review

A phase is accepted by evidence, not by opinion: every acceptance criterion in the
brief passes with a pointer to the test, command or file that proves it, and the
phase-exit reviewers have no blocker left.

## Context

- `git status --short` (must be clean) and `git log --oneline` since the phase began.
- `make check 2>&1 | tail -40 || true`: a failure is evidence, not a reason to stop.
- The acceptance criteria with ids, from the phase's plan in `.autopilot/plans/` or,
  if it's gone, re-derived from the brief.

## Steps

1. Branch `docs/phase-<id>-exit` from `main`.
2. Spawn `test-reviewer`, `determinism-auditor` and `coherence-auditor` (whole repo) **in
   one turn**, each with the phase id, the criteria with ids and the brief's line range.
3. Merge their reports into one table. The fixed formats make this mechanical:

   | Criterion | Result | Evidence | From |
   |---|---|---|---|
   | A1: … | PASS / FAIL | `tests/…::test_…`, command output, `path:line` | test-reviewer |

   Then the **must-fix list**: every FAIL and every Critical finding, deduplicated.
4. Fix the must-fix list on this branch, or in its own PR first when the fix is a
   code change too big to land with the phase-exit records. Re-run only the reviewer
   whose FAIL a fix addressed.
5. When every criterion passes: in `docs/PROGRESS.md`, tick the phase, set **Current
   phase** to the next one and **Next step** to its first step (`phase-start`). Make
   the same phase change in `README.md`'s status section (the records check compares
   the two), and add the table to the PR body.
6. At **Phase 1's** exit, the same PR sets `"frozen": true` in
   `config/preregistration.json`: the owner's approval of this PR signs off the evaluation
   design (brief §4, Pre-registration). Request that review as for any guardrail change.
7. The PR body carries the line `Phase exit: <id>`. That makes the merge gate require
   all three phase-exit reports as well as the per-PR ones (CLAUDE.md, Which reviews).
8. Continue with skill `autopilot`, step 4.

A criterion that can't pass without changing the brief (it's unreachable, or wrong) is
a decision: put it through `plan-critic` and `plan-arbiter` (autopilot step 2). Never
edit a criterion to make it pass.
