# Security

## Reporting a vulnerability

Report privately through GitHub: **Security → Report a vulnerability** on this
repository. Please don't open a public issue. You'll get an acknowledgement within a week.

Issues and PRs from outside contributors are welcome, but this repository is maintained
by an autonomous loop (ADR 0001) that never takes instructions from issue or PR text, and
never merges a PR from a fork. A maintainer reviews outside contributions by hand.

## What fieldtest handles

- **One API key** (`MISTRAL_API_KEY`), read from the environment by the provider SDK. It
  lives in a local, gitignored `.env`; CI has no key and runs in replay mode.
- **Public documents only** (French public tender notices from open data). Each dataset's
  source and licence are in its `data/<name>/DATASET.md`.
- **No user data and no network service** before Phase 5. The Phase 5 API binds to
  `127.0.0.1` by default.

## What is checked before anything is published

The repository is public from its first commit (ADR 0002). One rule set,
[`scripts/guard_rules.py`](scripts/guard_rules.py), runs at every point text can leave the
machine:

| Rule | Blocks |
|---|---|
| Private paths | `.private/`, `.env` and `.env.*` (not `.env.example`), `CLAUDE.local.md`, key and credential files |
| Secrets | Private key blocks, `sk-` keys, GitHub, AWS, Google, Slack and Hugging Face tokens, JWTs, secret-named assignments of long literals; plus gitleaks |
| Personal data | Absolute home-directory paths; email addresses other than noreply and `example.com` (public source documents under `data/` excepted) |
| Private terms | Any term in the local, gitignored `.private/denylist.txt` |
| Identity | Commit authors and committers must use a GitHub noreply address |
| Form | Conventional Commit subjects for commits and PR titles |

Where it runs:

1. **While writing**, as a Claude Code hook on every file write and every command that
   publishes text (commits, tags, PR and issue bodies and the files they name).
2. **At commit:** staged changes and the message (pre-commit), with gitleaks and
   `detect-private-key`.
3. **At push:** every commit not yet on `origin`, with gitleaks.
4. **In CI** (`security` job, required): gitleaks over the full history, the guard over
   the PR's commits **using main's copy of the guard**, so a PR can't weaken the rules
   it's judged by, and `pip-audit` over the locked dependencies. The `check` job runs
   zizmor over the workflows.
5. **At merge:** `scripts/guard.py --pr` checks the PR's title, body, diff, commits,
   checks and reviews, and refuses PRs from forks.
6. **On GitHub:** secret scanning with push protection, Dependabot alerts and updates,
   private vulnerability reporting, and a `main` ruleset (PR only, squash only, the
   `check` and `security` checks from GitHub Actions, no force push, no bypass).

Workflows run with a read-only token, pin every action by commit SHA, and never use
`pull_request_target`.

## If a secret is published

A secret that reaches a pushed commit is compromised, even if a later commit removes
it. Rotate it at the provider first, then clean the history. The loop escalates this to a
human at once instead of fixing it itself.
