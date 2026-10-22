---
name: fieldtest-pr
description: >
  How pull requests are shaped in fieldtest: one coherent change per PR, the title as
  the squash commit, branch names, and what goes in each section of the PR template,
  including what the merge gate reads. Read this BEFORE writing a PR title or body
  (autopilot step 4). fieldtest-voice governs the wording; CLAUDE.md owns the gate.
---

# fieldtest-pr

## One change per PR

A PR carries **one coherent change**: a feature, a fix, a refactor, a dependency bump,
or related changes to one area that land together. Size follows the change, but never
two unrelated changes: each PR costs a full review round, so batch what belongs together
and split what doesn't. A phase is usually several PRs, merged in order.

- A fix found while building something else is its own PR, or a line in
  `docs/PROGRESS.md` under the step that owes it. Never a drive-by edit.
- A pure move or rename lands before the behaviour change that needs it.
- Generated files (`uv.lock`, snapshots, a recorded cache) travel with the change that
  caused them, and the body says they're generated.
- Guardrail files (CLAUDE.md → Guardrails) go in their own PR when possible, since that
  PR waits for the owner's approving review.

Branch: `<type>/<slug>` (`feat/score-outcomes`, `fix/cache-atomic-write`).

## The title is the commit on `main`

Squash merge: the title becomes the one commit on `main`, so it is a Conventional Commit
subject (skill `fieldtest-voice`). The guard and the merge gate both check it.

## Body

Fill every section of `.github/pull_request_template.md`, in order, whatever the size;
a small PR keeps each to a line. Delete the template's HTML comments. Write the body to
a file under `.autopilot/` and pass it with `--body-file` and an absolute path (the
guard reads it).

- **Summary.** The problem, then what this PR changes. Then the brief step, the ADR and
  any follow-up, each "none" when there isn't one. A phase-exit PR adds the line
  `Phase exit: <id>`, which the merge gate reads.
- **Changes.** One line per file or unit. Generated files marked as generated.
- **Impact.** All five lines, each "none" only after checking: determinism, evaluation,
  security and privacy, guardrails, compatibility.
- **Validation.** One box per pre-PR gate step that applied, naming the command or
  agent and what it showed. An unticked box means not done.
- **Records updated.** Each record touched (CLAUDE.md → Records), or "none implied"
  after checking the map. `docs/PROGRESS.md` is always on the list.
- **Not done.** Deliberate omissions, discarded options (one sentence each, with why),
  deferred checks and open risks, each with where it's tracked. "Nothing" when true.
