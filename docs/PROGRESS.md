# Progress

The state of fieldtest against [the brief](../PROJECT-BRIEF.md). Every PR updates this
file: it ticks its step, moves **Next step**, and adds a log line. The block between the
status markers is what the `SessionStart` hook prints into every session.

<!-- status:start -->
- **Current phase:** 0A — Repo, tooling and Claude Code workflow
- **Next step:** PR 1 (#1): implement the owner's decisions on issue #2 on `build/phase-0a-workflow`, re-run `security-reviewer`, then request the owner's approving review. Then `merge-gate`, then Phase 0A's acceptance (skill `phase-review`).
- **Blocked on:** issue #2 (`security`): PR 1's reviews found that code the sandbox can write runs outside it next to real secrets (F1), and that GitHub doesn't enforce the owner's approval of a guardrail change (F2).
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
- [x] Prerequisites §12, steps 1–4 done by the human (repo published, App `fieldtest-loop-jessicafalcon` installed, `preflight --online` passes); `.github/loop-identity.json` filled in
- [x] Sandbox trial run under the driver: `uv`, pre-commit, git and gh work inside it; a non-allowlisted host is denied (403 from the proxy); Python's TLS trusts the proxy's certificate; the existing `allowWrite` cache paths suffice. It found four fixes, made in PR 1: pytest stats `.env` and `.private/` while collecting, so they are `--ignore`d; the driver's git identity and flag leaked into the tests, so `tests/conftest.py` removes them; the file fixers wrote on push, so they run on commit only; and the session can't read `.env`, so the driver writes its preflight report for it. Also unreadable inside it: CI logs (`results-receiver.actions.githubusercontent.com` isn't allowlisted). Unverified: that a sandboxed command sees only the placeholder key (the bash policy refuses to expand it); owed to Phase 0B's smoke call.
- [ ] PR 1 opened by the loop's App (#1, done), approved by the owner, merged by `merge-gate`. Once approved, check that a guardrail PR's `security` check turns green on the review event and that `merge-gate` reads the newest run (code-reviewer M1)
- Owed by the acceptance: skill `autopilot` step 4 says `git push -u`, but the sandbox denies writes to `.git/config`, so the upstream isn't recorded (the push succeeds). Drop `-u` (a guardrail change).
- [ ] Acceptance (`phase-review`): `make check` green; `/hooks` lists the hooks; an edit to `cache/llm/` is blocked; a commit with a fake API key is blocked; a commit staging `.private/` is blocked; the loop takes Phase 0A through `phase-review` end to end

## Phase 0B — Decisions and data spike

- [ ] Plan (`phase-start`)
- Owed from 0A: the smoke call shows the sandbox's masked key works only against `api.mistral.ai`.
- Owed: brief §12, step 5 (the Mistral key in `.env`, training opted out). If it isn't done by the time the smoke call needs it, the loop escalates (`human-action`) and builds the rest meanwhile.

## Phases 1–6

Not started. Each begins with `phase-start`, which writes its PR list here.

## Log

One line per merged PR: `#N` · title · what it closed.

- #1 · feat(loop): add the public-repo guard, hooks, CI and the autonomous delivery loop · Phase 0A's tooling, the loop, its identity and sandbox; the sandbox trial run
