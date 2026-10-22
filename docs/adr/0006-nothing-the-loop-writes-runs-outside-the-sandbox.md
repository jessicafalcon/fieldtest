# 0006. Nothing the loop writes runs outside the sandbox, and GitHub enforces the owner's approval

Status: Accepted
Date: 2026-10-22

## Context and Problem Statement

PR 1's security review (issue #2) found two blockers in ADRs 0003–0005.

- **F1: writable code runs next to the secrets.** The sandbox confines the loop's shell
  commands, but several things run outside it: the hooks (`scripts/guard.py`,
  `.claude/hooks/*`, and `.venv/bin/ruff` through the format hook), the driver's token
  refresh (from `.venv`), and your own `git commit` and `make check` (the same `.venv`,
  `.git/hooks` and tool caches). All of these were writable from inside the sandbox. A file
  the loop dropped there, such as a `.pth` in `.venv`, would run with `.env` readable.
- **F2: GitHub didn't enforce the owner's approval.** Only the PR's own CI enforced it, and
  the App had Workflows write, so a loop PR could have rewritten the check that judges it.

## Considered Options

1. Run the driver and the hooks from a write-protected snapshot of `main` only.
2. Run the loop as a separate OS user now.
3. Write-deny, inside the sandbox and for the file tools, everything that later runs outside
   it. Have only the driver install tooling, and make the approval a GitHub rule. Run the
   loop as a separate OS user before Phase 0B.

## Decision Outcome

Chosen option: **3**, the owner's choice on issue #2, because it closes both paths now
and leaves the remaining shared ground (one checkout, one `.venv`) to the OS-user step
before any model key exists.

**Isolation (F1)**

- `scripts/render_sandbox.py` denies writes to every guardrail path, plus `.venv`,
  `.git/hooks`, `.git/config` and the uv and pre-commit caches. It applies the denial twice:
  as sandbox `denyWrite` for shell commands, and as `Edit` permission rules for the file
  tools, which run outside the sandbox.
- Under the driver, `protect_files.py` also refuses those writes, and any write outside
  the project except temp dirs.
- `pyproject.toml`, `Makefile`, `scripts/preflight.py` and the renderer become guardrails.
- The driver runs `uv sync --frozen` and `pre-commit install-hooks` before each run, through
  the trusted cache. It runs its own scripts with `.venv/bin/python -I`.
- The session gets a throwaway uv cache in `.autopilot/`.
- Hooks run with `python3 -I`, and the scripts append their own folder to `sys.path`
  instead of putting it first, so a dropped `json.py` can't shadow the standard library.
- The format hook is off under the driver.
- The sandbox denies reads of the home folder except the repo and its tools, because
  `~/.config` also holds other credentials.
- The loop can no longer write a guardrail. It proposes the patch in a `guardrail` issue,
  and the owner applies it from an interactive session.

**Approval (F2)**

- `.github/CODEOWNERS` gives the owner every guardrail path. It is generated from
  `GUARDRAIL_PATHS` and kept equal to it by a test.
- The `main` ruleset requires a code owner's review and dismisses it on a later push. It
  has no bypass actors.
- The App loses Workflows write, so a loop PR can't change the CI that judges it.

### Consequences

- Good, because code the loop writes now runs only inside the sandbox, and the owner's
  approval of a guardrail change is a GitHub rule, not only a CI check.
- Good, because the remaining gap is named and dated: the owner's own commands share one
  checkout with the loop until the separate OS user exists (PROJECT-BRIEF.md §12).
- Bad, because a guardrail fix now needs the owner twice: once to apply it, once to
  approve it.
- Bad, because the bash policy reads command text, so a command run through an interpreter
  isn't checked. The merge-gate-only rule is policy. GitHub enforces checks and approval;
  it doesn't enforce which agent clicks merge.
