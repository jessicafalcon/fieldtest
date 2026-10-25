---
name: fieldtest-craft
description: >
  How code is written in fieldtest: the reuse-first ladder, stage and module shape,
  typing, Pydantic contracts, the provider interface, config and knowledge files,
  Typer, Jinja2, FastAPI and React conventions, and tooling (uv, ruff, mypy, pytest,
  pre-commit). Read this BEFORE writing or refactoring any Python, YAML config,
  template or frontend code, or choosing a dependency. Pairs with determinism-contract,
  fieldtest-resilience, fieldtest-security and fieldtest-voice.
---

# fieldtest-craft

fieldtest is small on purpose: a deterministic core of pure functions over files,
with the model behind one interface and the clock, environment and network at the
edges. Every file should read as one hand: quiet, typed, and covered by a check.

## Reuse before writing

Trace the real flow end to end first, then stop at the first rung that holds:

1. **Does it need to exist?** Built for the current phase only (brief §11.7). A
   speculative need: skip it, and say so in one line.
2. **Already in the repo?** Reuse the contract, helper or stage that's here.
3. **Standard library?** `pathlib`, `hashlib`, `json`, `decimal`, `unicodedata`, `enum`.
4. **An installed dependency?** Pydantic, Typer, Jinja2, the provider SDK.
5. **Only then** write the minimum that works.

No abstraction with one implementation (the provider interface is the brief's one
exception: an API provider and a local one), no factory for one product, no config for
a value that never changes. A deliberate shortcut gets a `# ponytail:` comment with its
ceiling and the trigger to upgrade.

## Layout and module shape

- One import root, `fieldtest`: `src/fieldtest/core/` (llm, ledger, hashing, config,
  normalizers) is shared with the extensions; `src/fieldtest/` holds ingest, extract,
  score, compare, report and `cli.py`; `src/fieldtest/api/` arrives in Phase 5a.
- One job per module (`score.py`, `compare.py`), no `utils.py`. Each opens with a
  one-line docstring and `from __future__ import annotations`, and declares `__all__`.
- **Pure core, I/O at the edges.** A stage reads its inputs, calls pure functions,
  writes one artifact under `runs/<run_id>/`, and appends ledger events. Paths, `now`,
  seeds and thresholds are parameters; only `cli.py` and `api/` read the clock and the
  environment.
- **The CLI is thin.** Typer commands parse arguments, load config, call a stage.

## Typing and contracts

- Modern typing (`X | None`, `list[str]`), every public signature typed. mypy runs
  lenient (brief §6): it checks bodies, and doesn't demand annotations on private
  helpers. `Any` is a smell.
- Every record that crosses a boundary (config, gold item, prediction, ledger event,
  result) is a Pydantic v2 model with `ConfigDict(frozen=True, extra="forbid")`. A fixed
  vocabulary (outcomes, event types, cache modes) is a `StrEnum`.
- A contract change bumps a `schema_version` recorded in the manifest. Never reshape a
  contract silently.

## Business knowledge lives in files (brief §3.4)

Use cases, field schemas, normalizers, thresholds, prompts and prices are YAML or
Markdown under `usecases/` and `config/`, loaded into Pydantic models that reject
unknown keys. Code never hardcodes a threshold, a price or a prompt. A new use case is
config plus data, with zero engine changes (Phase 7's acceptance).

## The model edge

- `core/llm/` exposes `complete(request) -> response`. The cache wraps it; providers
  implement it. Nothing else imports a provider SDK (the determinism guard).
- Rate limiter in the client (requests/second from config, default 1), HTTP 429 and 5xx
  retried with backoff within a budget (skill `fieldtest-resilience`).

## Templates, API, UI

- Jinja2 with `autoescape=True`, `StrictUndefined`, sorted iteration, no `now()` in a
  template. Filters are pure functions with doctests.
- FastAPI (Phase 5a): routers thin like the CLI, status derived from the ledger, input
  models on every route (skill `fieldtest-security`).
- React + Vite + TypeScript (Phase 5b): strict TS, no `any`, three screens only.

## Tooling

- **uv**: `uv sync --locked` in CI, `uv run --frozen` everywhere after it.
- **ruff** format and lint, fixed on every edit by the `format_python.py` hook.
- **mypy** (`make typecheck`), **pytest** with doctests and `--disable-socket`.
- **pre-commit** runs all of it, plus gitleaks, zizmor, the determinism guard and
  `scripts/guard.py`. `make check` is the local gate.
- Python 3.12, pinned in `.python-version`.

Let the hooks do the mechanical enforcement. Spend attention on the logic and on the
check that proves it.
