# Progress

The state of fieldtest against [the brief](../PROJECT-BRIEF.md). Every PR updates this
file: it ticks its step, moves **Next step**, and adds a log line. The block between the
status markers is what the `SessionStart` hook prints into every session.

<!-- status:start -->
- **Current phase:** 0A — Repo, tooling and Claude Code workflow
- **Next step:** PR 1 (`build/phase-0a-workflow`). Once the prerequisites are done, the first `scripts/autopilot.sh` iteration pushes the branch as the loop's App, opens PR 1, runs the reviews and requests the owner's approval: PR 1 creates every guardrail. After the approval, `merge-gate` merges it. Then Phase 0A's acceptance (skill `phase-review`).
- **Blocked on:** the human prerequisites in PROJECT-BRIEF.md §12, steps 1–4 (tools, GitHub settings, the loop's GitHub App, publishing). `python3 scripts/preflight.py --all` lists what's missing.
<!-- status:end -->

## Phase 0A — Repo, tooling and Claude Code workflow

- [x] Repo skeleton (brief §6): `src/fieldtest/`, `config/`, `usecases/`, `data/`, `cache/llm/`, `tests/`
- [x] `uv`, `ruff`, `mypy`, `pytest`, pre-commit, Makefile (`make check` = lint + types + tests + records)
- [x] `.gitignore` for `.env*`, `.private/`, `CLAUDE.local.md`, `runs/`
- [x] `CLAUDE.md`, `docs/PROGRESS.md`, `docs/adr/0000-template.md`; ADR 0001 (the autonomous loop), ADR 0002 (public from the first commit)
- [x] `scripts/guard.py` wired as the git pre-commit, commit-msg and pre-push hook, the Claude Code hook, the CI guard and the merge gate's check
- [x] Hooks, skills and agents (brief §9), with unit tests for every hook script
- [x] CI (`check`, `security`), Dependabot, PR template, `SECURITY.md`, MIT licence
- [x] The loop's own GitHub identity (ADR 0003): `scripts/loop_auth.py`, `.github/loop-identity.json`, guardrail approval by the owner's review on the head commit
- [x] Human prerequisites (brief §12) and `scripts/preflight.py`; every key in `.env`, with `.gitignore`'s secret lines locked
- [x] Pre-registration (ADR 0004): `config/preregistration.json`, guarded regions in the brief and `CLAUDE.md`, the agents and authority skills as guardrails
- [x] The loop's sandbox (ADR 0005): `.claude/sandbox.autopilot.json`, the masked model key, no `--env-file`
- [x] Gold labels text-grounded with evidence spans, in the plan (brief §4; built in Phase 1)
- [ ] Prerequisites §12, steps 1–4 done by the human; `.github/loop-identity.json` filled in
- [ ] Sandbox trial run under the driver: `uv`, pre-commit, git and gh work inside it; a sandboxed command sees only the placeholder key; a non-allowlisted host is denied. Unverified so far: whether Python's TLS trusts the proxy's certificate, and which cache paths need `allowWrite`
- [ ] PR 1 opened by the loop's App, approved by the owner, merged by `merge-gate`
- [ ] Acceptance (`phase-review`): `make check` green; `/hooks` lists the hooks; an edit to `cache/llm/` is blocked; a commit with a fake API key is blocked; a commit staging `.private/` is blocked; the loop takes Phase 0A through `phase-review` end to end

## Phase 0B — Decisions and data spike

- [ ] Plan (`phase-start`)
- Owed: brief §12, step 5 (the Mistral key in `.env`, training opted out). If it isn't done by the time the smoke call needs it, the loop escalates (`human-action`) and builds the rest meanwhile.

## Phases 1–6

Not started. Each begins with `phase-start`, which writes its PR list here.

## Log

One line per merged PR: `#N` · title · what it closed.

- (none yet)
