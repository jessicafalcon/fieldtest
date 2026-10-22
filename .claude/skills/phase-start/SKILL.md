---
name: phase-start
description: >
  Start a phase of PROJECT-BRIEF.md: restate its deliverables and acceptance criteria,
  split it into PRs, list the files and the tests to write first, name the open
  questions, then put the plan through plan-critic and plan-arbiter. Writes no code.
  Use at the first step of every phase (autopilot step 1), or when asked to plan one.
argument-hint: "[phase id, e.g. 1 or 3b]"
---

# phase-start

Plan one phase so that the arbiter, not a human, can approve it. The output is a plan
file and the arbiter's rulings, not code.

## Inputs

- The phase's section in `PROJECT-BRIEF.md` §7 (or §8 for an extension). Read only it,
  plus the sections it cites (§3 principles, §4 contract, §6 architecture).
- `docs/PROGRESS.md`: what is already done, and any work owed to this phase.
- `docs/adr/`: decisions the phase must respect.
- `git log --oneline -20`.

## The plan (`.autopilot/plans/phase-<id>.md`)

1. **Deliverables and acceptance**, quoted from the brief. Each acceptance criterion
   gets an id (`A1`, `A2`, …), so the test-reviewer can map tests to it later.
2. **Open questions.** Anything the brief leaves open, with the options and a
   recommendation. Resolve them from the brief's principles where you can; the
   arbiter rules on the rest.
3. **PR split.** One coherent change per PR (skill `fieldtest-pr`), in order, each
   ending green and useful. For each: branch name, files, the tests written first, and
   the acceptance criteria it closes. A pure move or rename goes before the behaviour
   that needs it.
4. **Risks.** What could make an acceptance criterion unreachable, and the cheapest
   early PR that would show it.
5. **Human-only steps.** Anything the loop cannot do (brief "Manual step (human)",
   credentials, console settings). Each must already be in the brief's §12 prerequisites.
   A new one goes into §12 in the phase's first PR, and `scripts/preflight.py` gains its
   check. Run `python3 scripts/preflight.py` now: a prerequisite this phase needs that
   isn't met is escalated at once (`human-action`), so the human can act while the loop
   builds what doesn't depend on it.

## Then

1. Spawn `plan-critic`, then `plan-arbiter` (skill `autopilot`, step 2).
2. Apply the rulings to the plan file.
3. Write the PR list into `docs/PROGRESS.md` under the phase (checkboxes), and move
   **Next step** to the first PR. This lands as the first commit of the phase's first PR.
4. Continue with skill `autopilot`, step 3.
