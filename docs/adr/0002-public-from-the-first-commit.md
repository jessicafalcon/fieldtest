# 0002. Publish from the first commit, behind layered guards

Status: Accepted
Date: 2026-10-21

## Context and Problem Statement

The repository is public from its first push, so every commit, message, PR, comment and
issue is published as it lands, and git history keeps it forever. The project also holds
private material that must never be published (personal notes, a private-terms list), and
it will hold an API key in `.env`. An autonomous loop writes most of the text. What has to
be true before anything is pushed or merged, and where is each check enforced?

## Considered Options

1. **Private until done, then publish.** A history scrub before publishing is error-prone,
   and the work is wanted in the open from the start.
2. **Public, relying on GitHub's secret scanning.** It catches known provider tokens after
   the fact and knows nothing of private terms, personal data or paths.
3. **Public, with the same rules enforced at every point text can leave the machine**,
   and again server-side.

## Decision Outcome

Chosen option: **3**, because a single check at one point would miss whatever reaches
GitHub by another route.

One rule set, `scripts/guard_rules.py`, runs at every exit:

| Point | Check |
|---|---|
| Claude Code writes a file or publishes text | `guard.py --hook` (PreToolUse); `protect_files.py`; `bash_policy.py` blocks hook bypasses and secret reads |
| `git commit` | `guard.py --staged` and `--commit-msg`, gitleaks, `detect-private-key` |
| `git push` | `guard.py --push` over every commit not yet on `origin`, including the author emails, plus gitleaks |
| A PR | CI `security`: gitleaks over the whole history, main's guard over the PR's commits, `pip-audit`; CI `check`: zizmor and the rest |
| The merge | `guard.py --pr`: the PR's title, body, diff, commits and reviews |
| GitHub | Secret scanning with push protection, Dependabot alerts, private vulnerability reporting, the `main` ruleset |

The rules: no private path (`.private/`, `.env*`, `CLAUDE.local.md`, key files); no
secret shapes; no personal data (home-directory paths, personal emails); no term from the
gitignored `.private/denylist.txt`; Conventional Commit subjects; noreply identities only.

This also settles the brief's D6 earlier than Phase 0B: a public repository needs a
licence on its first push, so it ships with the brief's default, **MIT**.

### Consequences

- Good, because a leak has to get past several independent checks, one of them
  server-side and run from main's code.
- Good, because the denylist itself never lands: it lives in `.private/`, and only the
  local hooks apply it. CI applies every other rule.
- Bad, because the denylist rule doesn't run in CI or for commits made on another machine
  without the file. The guard says so in its docstring, and the PR-time check runs locally
  in the merge gate.
- Bad, because pattern checks have false positives. The fix is to reword the content
  (a placeholder, `example.com`, a repo-relative path), never to weaken the rule. Tests
  build their fake secrets at runtime for the same reason.
