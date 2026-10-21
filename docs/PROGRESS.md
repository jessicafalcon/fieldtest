# Progress

The state of fieldtest against [the brief](../PROJECT-BRIEF.md). Every PR updates this
file: it ticks its step, moves **Next step**, and adds a log line. The block between the
status markers is what the `SessionStart` hook prints into every session.

<!-- status:start -->
- **Current phase:** 0A — Repo, tooling and Claude Code workflow
- **Next step:** merge PR 1 (`build/phase-0a-workflow`). It creates every guardrail, so it waits for a human's `human-approved` label. Then Phase 0A's acceptance (skill `phase-review`).
- **Blocked on:** nothing.
<!-- status:end -->

## Phase 0A — Repo, tooling and Claude Code workflow

- [x] Repo skeleton (brief §6): `src/fieldtest/`, `config/`, `usecases/`, `data/`, `cache/llm/`, `tests/`
- [x] `uv`, `ruff`, `mypy`, `pytest`, pre-commit, Makefile (`make check` = lint + types + tests + records)
- [x] `.gitignore` for `.env*`, `.private/`, `CLAUDE.local.md`, `runs/`
- [x] `CLAUDE.md`, `docs/PROGRESS.md`, `docs/adr/0000-template.md`; ADR 0001 (the autonomous loop), ADR 0002 (public from the first commit)
- [x] `scripts/guard.py` wired as the git pre-commit, commit-msg and pre-push hook, the Claude Code hook, the CI guard and the merge gate's check
- [x] Hooks, skills and agents (brief §9), with unit tests for every hook script
- [x] CI (`check`, `security`), Dependabot, PR template, `SECURITY.md`, MIT licence
- [ ] PR 1 merged by `merge-gate` after the `human-approved` label
- [ ] Acceptance (`phase-review`): `make check` green; `/hooks` lists the hooks; an edit to `cache/llm/` is blocked; a commit with a fake API key is blocked; a commit staging `.private/` is blocked; the loop takes Phase 0A through `phase-review` end to end

## Phase 0B — Decisions and data spike

- [ ] Plan (`phase-start`)
- Owed: the human creates the Mistral API key, opts out of training on API data, and fills `.env`. The loop escalates (`human-action`) when the smoke call needs it.

## Phases 1–6

Not started. Each begins with `phase-start`, which writes its PR list here.

## Log

One line per merged PR: `#N` · title · what it closed.

- (none yet)
