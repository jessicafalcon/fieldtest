---
name: determinism-contract
description: >
  The determinism contract of PROJECT-BRIEF.md §4 and the invariants that keep a
  fieldtest result reproducible and honest, as a checklist: pinned models, fixed
  parameters, record/replay cache, validate-then-normalize, pure scorers, the run
  manifest, stable ordering, template-rendered reports, asymmetric outcomes, and
  nothing dropped silently. Loads when working on src/ or tests/; preloaded into
  code-reviewer and determinism-auditor.
user-invocable: false
paths:
  - "src/**"
  - "tests/**"
---

# determinism-contract

**Definition:** the same manifest inputs plus the same cache produce byte-identical
`predictions.jsonl`, `results.json` and `report.html`. A change that computes the right
number but breaks this is a defect.

## The eight rules (brief §4), as checks

1. **Pinned models.** Every model ID comes from `config/models.yaml` and is dated. No
   `*-latest`, no ID typed in code.
2. **Fixed parameters.** `temperature=0`, `random_seed` where the provider has one,
   JSON-schema structured output. The parameters are part of the cache key.
3. **Record/replay cache.** Every LLM call goes through `core/llm/`'s cache, keyed by
   `sha256(canonical_json({provider, model, messages, params, response_schema}))`, stored
   at `cache/llm/<hash>.json`. Modes `record`, `replay` (a miss is an **error**: CI and
   demos), `off` (variance checks only). No code path reaches a provider without the
   cache. `cache/llm/` is written by code only (the `protect_files` hook).
4. **Validate, then normalize.** Pydantic v2 at the boundary. Dates to ISO 8601, amounts
   to `Decimal`, strings NFC, trimmed, whitespace collapsed. Field normalizers come from
   the use-case config. Unknown, malformed or missing values become typed failures
   (`invalid`), never guesses.
5. **Pure scorers.** No I/O, no clock, no randomness, no LLM-as-judge in v1.
6. **Run manifest.** `manifest.json` records the git SHA, config, dataset and prompt
   hashes, provider and model IDs, cache mode and package versions. Wall-clock time lives
   **only** in the manifest and `ledger.jsonl`, never in a hashed output.
7. **Stable ordering.** Sort items by ID everywhere; JSON with `sort_keys=True` and a
   fixed separator; no set or dict order leaks into an output.
8. **Template-rendered reports.** Jinja2 from `results.json`; a snapshot test proves the
   same input renders byte-identical HTML. No LLM writes report text.

## Where the clock, environment and network may appear

Only `src/fieldtest/core/llm/` (providers, cache I/O), `src/fieldtest/cli.py` and
`src/fieldtest/api/`. They read the clock, environment and network, then pass values
into the core as parameters (`now`, `run_id`, config). The `determinism_guard.py` hook
flags the rest on every edit; pre-commit runs the same check.

## Invariants beyond §4

- **Asymmetric outcomes.** `correct`, `missing`, `wrong`, `hallucinated`, `invalid`,
  `call_failed`, as the brief's taxonomy defines them. Never fold `wrong` or
  `hallucinated` into a single score with `missing`; never optimize one aggregate.
- **The recommendation rule is code.** The cheapest model with
  `accuracy ≥ min_accuracy` and `unsafe_rate ≤ max_unsafe_rate`, ties by model ID, else
  `NOT_READY` with the blocking fields. Thresholds come from the use-case config.
- **The ledger is append-only.** Every step writes a typed event; state is derived from
  the ledger, so a rerun converges to a no-op. Extensions add event types and never
  change existing ones.
- **Nothing disappears silently.** A failed call, an invalid output or a skipped document
  is an event and a count in `results.json`. A stage that drops an item without a
  counter is a bug.
- **Gold labels are evidence.** A committed `gold.jsonl` changes only through the
  labeling script under a new ADR (the `protect_files` hook), and never to make a model
  look better.

## Review checklist

1. Each rule above, on the diff.
2. Would a second run on another machine, with another `PYTHONHASHSEED`, produce the same
   bytes? Look for ordering, clock, float formatting and locale leaks.
3. Is there a test that fails if this breaks (skill `fieldtest-tests`)?
