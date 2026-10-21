---
name: fieldtest-voice
description: >
  The written voice of fieldtest: commit messages, PR titles and bodies, review and
  fix-log comments, escalation issues, code comments, docstrings, decision records and
  every Markdown file. Engineering register: result first, mechanism and consequence
  stated precisely, validation stated honestly, nothing promotional, nothing about who
  the project is for. Read this BEFORE writing a commit, PR, issue, comment, docstring
  or any .md file.
---

# fieldtest-voice

Prose here reads like an engineer explaining a change to a colleague who will maintain
it: what changed, the mechanism, the consequence, how it was checked. Precise over short,
never padded.

## Public by default

Every commit, PR, comment and issue is public and permanent. Describe the tool and what
it does, never who it is for or why it was built (brief §11.9). Never frame the project as
a portfolio piece or an application, and never name an organization as the reason for a
choice. The guard blocks the known private terms, but the rule is the wording, not the
list.

## Commit messages

Conventional Commits; the guard enforces the form.

- **Types:** `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`, `build`,
  `revert`. Pick by what the change does for a user of the tool.
- **Scope** is the area touched: `feat(score):`, `fix(guard,ci):`, `build(deps):`.
- **Subject: the change and its effect**, imperative, lowercase, no period, about 72
  characters at most. Keep the why in the subject with "so" or "instead of" when it fits:
  `fix(llm): treat 429 as retryable so a rate-limited run completes`.
- **Body** (optional, wrapped at 72): the mechanism, and the reason for any new dependency.
- Claude-authored commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## PRs, reviews, fix logs, issues

- PR title: a commit subject (it becomes the squash commit on `main`). The body follows
  `.github/pull_request_template.md` (skill `fieldtest-pr`) and ends with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Root causes are mechanistic.** Name the function, value or ordering that fails and
  why. Bold the one consequence that matters.
- **Numbers with arrows:** `accuracy 81% → 88%`, `ruff 0.16 → 0.17`.
- **Validation is honest.** Name the command and what it showed, and what was not run.
- A review report is posted verbatim. A fix log has one line per finding, with what
  fixed it or why not.
- An escalation issue is written for a human arriving cold: what happened, what was tried,
  the exact steps needed, how to resume.

## Comments and docstrings

- Comments carry the *why*, the invariant, or the cost of getting it wrong, in full
  sentences. "Keep in sync with X" wherever two places must change together. `# ponytail:`
  marks a deliberate shortcut with its ceiling. No commented-out code; no TODO without a
  trigger.
- Module docstring: one line stating its job. Function: one imperative line, plus
  `Raises`, `Notes` or a doctest only when the signature isn't enough.

## Markdown

- Open with what it is, in one sentence. Then the result or the reason to care.
- Structure for scanning: plain headings, tables for options and thresholds, numbered
  procedures with a **bold lead term**.
- Factual, not promotional: "X, because Y" beats adjectives.
- Name limits and non-goals as design choices.
- **A spec has no changelog.** The brief states the current design as if it were always
  the plan; history lives in git and the ADRs.
- Paths are repo-relative or `~/`. Never an absolute home path (the guard blocks it).

## Decision records

`docs/adr/NNNN-short-title.md` from `docs/adr/0000-template.md`, numbered, never edited once
accepted (the `protect_files` hook): a later record supersedes it. Most fit on one screen.
