# 0003. The loop acts as its own GitHub App

Status: Accepted
Date: 2026-10-22

## Context and Problem Statement

ADR 0001 lets an autonomous loop build, review and merge, with a human approving only
changes to the guardrails. If the loop acted with the owner's GitHub identity, nothing on
GitHub could tell the loop from the owner. A label or a review "by the owner" could just as
well come from the loop, and the owner's token can change settings and rulesets. The
human approval would be a convention, not a boundary. What identity should the loop use,
and what should count as the owner's approval?

## Considered Options

1. **The owner's token, restricted by local hooks.** No setup. But it stops only accidents,
   and the approval is indistinguishable from the loop's own actions.
2. **A fine-grained personal access token** limited to this repository. It drops
   administration rights, but GitHub still sees the owner, so the approval problem remains.
3. **A machine-user account with its own token.** A separate identity, but it needs a
   second GitHub account and a long-lived token.
4. **A GitHub App installed on this repository only**, with Contents, Pull requests, Issues
   and Workflows write, Actions and Checks read, and no Administration. It authenticates
   with one-hour installation tokens minted from a private key.

## Decision Outcome

Chosen option: **4**, because it is a separate identity (`<app>[bot]`) with least
privilege, its credentials expire within the hour, and it needs no second account.

- **Approval is the owner's review on the head commit.** A guardrail PR merges only when
  the owner's latest review approves exactly its head commit. GitHub never lets a PR's
  author approve it, and the loop authors the PRs, so the loop can't satisfy this rule. A
  push after the approval moves the head and voids it. CI checks this with main's copy of
  the guard, re-running on every review, and GitHub enforces it through `CODEOWNERS` and a
  code-owner review in the ruleset (ADR 0006). This replaces the `human-approved` label, which
  the loop's own token could have added.
- **Keys stay in `.env`.** The App's ID, installation ID and private key (base64) live in
  `.env` beside the model key. `scripts/loop_auth.py` mints the token and never prints it.
  `scripts/autopilot.sh` writes it to a private gh config (`.autopilot/gh/`, mode 0600),
  refreshes it every 30 minutes, and deletes it on exit. It points git's credential helper
  at it, so no other credential on the machine is consulted, and it authors the loop's
  commits as the App's noreply identity.
- **Trust follows identity.** The PR guard trusts review-marker comments only from the
  loop's App or the owner (`.github/loop-identity.json`, a guardrail file), and accepts
  PRs authored by the owner, the App or Dependabot.

### Consequences

- Good, because the owner's approval and the repository settings are now beyond the
  loop's reach on GitHub's side, not only by local convention.
- Good, because every loop action is attributed to the bot in the public history.
- Bad, because it adds setup: creating and installing the App (PROJECT-BRIEF.md §12, steps
  3–4), and a development dependency (PyJWT) to sign the App's token request.
- Bad, because the loop still runs on the owner's machine, where the owner's own GitHub
  login exists. The hooks stop a session from switching to it by accident
  (`bash_policy.py`). Only running the driver as a separate OS user or in a container
  removes it from reach, which §12 offers as optional hardening.
