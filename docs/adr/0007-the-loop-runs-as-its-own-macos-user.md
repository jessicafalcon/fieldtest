# 0007. Run the loop as its own macOS user, make all of `.claude/` a guardrail, and have the owner merge workflow changes

Status: Accepted
Date: 2026-10-25

## Context and Problem Statement

ADR 0006 write-denied, inside the sandbox, every path known to run later outside it. The
re-review of PR #1 on that design (issue #3) found four more: a module in `src/` that
shadows a driver script through the editable install's `.pth`, forged bytecode in
`scripts/__pycache__/`, a `.git/commondir` that points git at a loop-written config, and a
`uv.lock` the driver installs as the branch has it. It was the second round in which the
deny list missed a route. With the driver run as the owner, any such route reaches the
owner's `gh` login (admin on the repository), SSH keys and keychain. The same review found
that Claude Code's sandbox write-denies all of `.claude/skills/`, so the loop can't commit
the five skills that weren't guardrails, and that an App without Workflows permission
can't merge a PR that changes `.github/workflows/`.

## Considered Options

1. **Patch each route:** keep `src/` off the driver's path, move bytecode to a denied
   prefix, write-deny `.git/commondir` and `worktrees/`, and refuse to sync a lockfile that
   differs from `main`'s.
2. **Run the loop as its own macOS user now,** before the driver runs again, instead of
   before Phase 0B.
3. **Both.**

## Decision Outcome

Chosen option: **2**, the owner's choice on issue #3, because it bounds what a missed route
reaches instead of relying on the deny list being complete. The loop's user holds only its
clone and its `.env`: an App installed on this one repository, with no Administration and
no Workflows permission, and later the Mistral key. It has no `gh` login of its own, since
the driver acts only as the App. The routes stay open within that user, so code that escapes
the sandbox can read the loop's own keys; that is the accepted residual.

Also decided on issue #3:

- **All of `.claude/` is a guardrail**, replacing the per-file list in ADR 0004 (settings,
  sandbox, hooks, agents and five skills). It matches what the sandbox already enforces: the
  owner applies and approves every change there.
- **The owner merges a PR that changes `.github/workflows/`.** The App keeps no Workflows
  permission, so a loop PR can't rewrite the CI that judges it. `merge-gate` verifies such a
  PR as usual and returns `ESCALATE human-action (owner merges)` with the verified head
  instead of merging.
- `.env.example` is readable again inside the sandbox (an `allowRead` exception to the
  `.env.*` denial), and the review agents' flag check refuses abbreviated and bundled forms
  of a writing flag (`--open=sh`, `-lOtrue`), failing closed on any bundle with `o`, `c` or
  `O`.

### Consequences

- Good, because a route the deny list misses reaches the loop's own scoped keys, not the
  owner's account, and because the owner's commands no longer share a checkout, `.venv` or
  hooks with the loop.
- Good, because the guardrail list for `.claude/` is one line that can't drift from the
  sandbox's own denial.
- Bad, because setting up the user is manual (brief §12), and the owner works from a
  separate clone.
- Bad, because the loop's keys are still readable by code that escapes the sandbox. Until
  it is revoked, a leaked App key can do on this repository what the loop does: push
  branches, open PRs, and merge one that passes CI and touches no guardrail. It can't merge
  a guardrail or workflow change, or change settings.
- Bad, because every workflow change now needs the owner twice: an approving review, then
  the merge.

<!-- Accepted records are never edited (the protect_files hook): a new record supersedes. -->
