# fieldtest

**Is an LLM good enough for your document task, which one, at what cost, and can you run
it yourself?**

fieldtest answers that with evidence instead of anecdotes. Give it a handful of real
documents and the answers you expect. It runs the same extraction on several models and
reports which one is good enough, how often each makes unsafe mistakes, what it costs per
1,000 documents, and whether it can run on your own infrastructure. The results are
deterministic and reproducible.

> **Status: in development, not usable yet.** The repository holds the plan and the
> delivery tooling. No product code has landed.

## Status

**Current phase:** 0A — Repo, tooling and Claude Code workflow

| Phase | What it delivers | State |
|---|---|---|
| 0A | Repo, tooling, guards, and the autonomous delivery loop with its own GitHub identity | In review (PR 1) |
| 0B | Pinned models and prices, decision records, five sample documents, one live smoke call | Next |
| 1 | Gold set, use-case config, pure scorers, `fieldtest score` | Planned |
| 2 | Deterministic extraction runner with record/replay cache and ledger | Planned |
| 3 | Multi-model comparison and the recommendation rule | Planned |
| 4 | HTML report | Planned |
| 5 | API, minimal UI, Docker | Planned |
| 6 | v1.0: CI replay eval, findings write-up | Planned |

The plan is [PROJECT-BRIEF.md](PROJECT-BRIEF.md); the detailed state is
[docs/PROGRESS.md](docs/PROGRESS.md).

## What it will do

A use case is a config file plus a small labeled sample. One command runs the same
extraction on several models and renders a report a non-technical reader understands in
a minute:

- **Field accuracy** and **unsafe error rate**, kept apart. A wrong or invented value is
  worse than a missing one, so the two are never folded into one score.
- **Estimated cost per 1,000 documents** from list prices, and **p50/p95 latency**.
- **Self-hostable or not**, measured on a local open-weight model rather than asserted.
- **A deterministic recommendation:** the cheapest model that meets the use case's
  accuracy and unsafe-error thresholds, or `NOT_READY` with the fields that block it.

Every model call goes through a record/replay cache, so a recorded run replays with no
network and no API key, byte for byte.

## How it's built

fieldtest is built by an autonomous loop in [Claude Code](https://claude.com/claude-code)
with Opus 5.5. A human steps in only for setup, for guardrail changes, and when the loop
escalates ([ADR 0001](docs/adr/0001-autonomous-delivery-loop.md)):

1. **Plan:** a critic agent stress-tests each phase's plan, and an arbiter agent rules on
   it under a fixed decision policy.
2. **Build:** hooks format code, protect files, and enforce the determinism contract on
   every edit.
3. **Review:** independent read-only agents review each PR (code, security, coherence),
   and their reports are posted on the PR.
4. **Merge:** a merge-gate agent checks CI, the deterministic PR guard and the reviews,
   then squash-merges the exact commit it verified. It is the only role allowed to merge.
5. **Its own identity:** the loop acts as a GitHub App without admin rights, so it can't
   approve its own PRs. A change to the guardrails merges only after the owner approves it
   ([ADR 0003](docs/adr/0003-the-loop-acts-as-its-own-github-app.md)).
6. **Pre-registered results:** what defines success (thresholds, gold labels, fields, the
   recommendation rule) is frozen before results are seen, and changing it needs the
   owner's approval ([ADR 0004](docs/adr/0004-pre-register-what-defines-success.md)).
7. **Escalate:** for credentials, money, goals or a security incident, the loop opens a
   `needs-human` issue and waits.

The workflow, its skills, agents and hooks are described in [CLAUDE.md](CLAUDE.md).

## Security

The repository is public from its first commit. The same guard checks for private paths,
secrets, personal data and private terms at every step: when a file is written, at commit,
at push, in CI (using main's copy of the guard) and at merge. gitleaks, zizmor, pip-audit
and GitHub's secret scanning run alongside it. Every key lives in a gitignored `.env`, and
the lines that ignore it can't be removed. The loop's commands run in Claude Code's sandbox,
where the model key is only a placeholder and the network is an allowlist. See [SECURITY.md](SECURITY.md) and
[ADR 0002](docs/adr/0002-public-from-the-first-commit.md).

## Setup

Everything a human provides, and when, is listed in
[PROJECT-BRIEF.md §12](PROJECT-BRIEF.md#12-human-prerequisites): tools, GitHub settings,
the loop's GitHub App, and the API keys, all of which go into `.env`
(template: [.env.example](.env.example)).

```sh
uv sync
uv run pre-commit install           # commit, commit-msg and pre-push hooks
python3 scripts/preflight.py --all  # what's ready and what's missing; never prints a key
make check                          # lint, types, tests, records
scripts/autopilot.sh                # run the loop
```

Commits use your GitHub noreply address and Conventional Commit subjects; the hooks refuse
anything else. Changes reach `main` only through squash-merged PRs.

## Design principles

Adapted from Orus Engineering, *How to build AI agents that actually work in prod*
(September 2026):

- Start with the feedback loop, not the model.
- Use the LLM for ambiguous input and code for consequences.
- Treat model output as a proposal, not a fact.
- Keep business knowledge in files.
- Render reports from templates.
- Count errors asymmetrically.
- Derive state from an append-only ledger.
- Test without the network.

## License

[MIT](LICENSE)
