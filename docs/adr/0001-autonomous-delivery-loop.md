# 0001. Deliver by an autonomous loop, with a human only on escalation

Status: Accepted
Date: 2026-10-21

## Context and Problem Statement

The brief's §9 workflow has two human approvals per phase: the plan after `/phase-start`,
and the work after `/phase-review`, plus the human merging each PR. fieldtest is to be
built with no human in the loop except when something technical fails or the workflow
cannot resolve a question. The approvals must be replaced by checks that are at least as
independent, and the controls that make the loop safe must not be ones the loop can
loosen by itself.

## Considered Options

1. **Keep the human approvals.** Safe and slow; it is what the brief described, and it
   is what this decision replaces.
2. **One agent plans, builds, reviews and merges.** Simple, but the author grades its own
   work, and an injected instruction or a slip reaches `main` unchecked.
3. **Separated roles plus a server-side boundary.** A critic and an arbiter replace plan
   approval. Independent read-only reviewers report on each PR. A merge gate that didn't
   build or review the PR verifies the evidence and is the only role allowed to merge.
   The GitHub ruleset and CI, running main's copy of the guard, enforce what no local
   process can bypass, and a change to the guardrails waits for a human label.

## Decision Outcome

Chosen option: **3**, because it keeps the separation of duties the human approvals gave
(author ≠ critic ≠ decider; builder ≠ reviewer ≠ merger) without the wait, and puts the
hard limits where the loop can't reach them.

- **Plan approval:** `plan-critic` re-derives the plan's claims from the sources and
  stress-tests each load-bearing decision; `plan-arbiter` rules on every finding by a
  fixed policy (the §4 contract, then public-repo safety, the phase's acceptance criteria,
  simplicity, reversibility, cost) and escalates only what that policy reserves for a human.
- **Phase acceptance:** evidence, not opinion. Every criterion PASS with a test or
  command, from `test-reviewer`, `determinism-auditor` and `coherence-auditor`.
- **Merge:** `merge-gate` runs `scripts/guard.py --pr`, which checks deterministically
  that the PR is the owner's, from this repo, green on `check` and `security`, carries the
  required review reports (by changed paths) and a fix log after them, updates
  `docs/PROGRESS.md`, and holds no private path, secret or personal data. The agent then
  judges whether each blocker and major finding was really fixed, and merges with
  `--match-head-commit`, so what merges is exactly what it verified.
- **Guardrails** (the list in CLAUDE.md and `GUARDRAIL_PATHS`): a PR that touches one
  merges only after a human adds `human-approved`. The loop may propose a guardrail
  change; it can't approve one.
- **Escalation** is a `needs-human` issue with exact instructions. The driver
  (`scripts/autopilot.sh`) stops while one is open, and a retry budget stops the loop
  from spinning.

### Consequences

- Good, because work proceeds between human visits, and the human's attention goes to
  the few decisions that need it: credentials, money, goals, and the guardrails themselves.
- Good, because every review, fix and merge decision is a public PR comment, so the audit
  trail is complete.
- Bad, because the loop acts with the owner's GitHub identity. The local hooks stop
  accidents and injected instructions, not a deliberate adversary holding that token.
  The boundary that holds even then is server-side: the ruleset (PR only, squash only,
  checks from GitHub Actions, no bypass actors) and CI's use of main's guard. Running the
  loop under a separate bot identity without admin rights would close the gap; it needs a
  second account and is left as a hardening step.
- Bad, because each PR costs several fresh-context agent runs. The review set is sized by
  what the PR changes (prose: one auditor; code: two reviewers; phase exit: three more).
