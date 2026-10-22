---
name: fieldtest-tests
description: >
  The testing standard for fieldtest: offline and deterministic always; doctests, unit,
  snapshot and determinism tests; the predictor fixtures that pin the scorers;
  record/replay tests for LLM behaviour; fault injection for every failure path; tests
  for hooks and guards; and how each acceptance criterion maps to a test. Read this
  BEFORE writing or changing a test, or deciding what a change must prove.
---

# fieldtest-tests

fieldtest's claims (same inputs, same bytes; a wrong value is never scored as safe; one
bad document never stops a run) are only as good as the tests that pin them. Tests
are offline (brief §3.9): `uv run pytest` needs no network, no API key and no clock.
`--disable-socket` makes any TCP connection fail the test that opens it.

## The bar

- **Every acceptance criterion** in the brief has at least one test that fails when the
  criterion breaks. Name the test after the behaviour:
  `test_perfect_predictor_scores_100_percent`, `test_replay_miss_is_an_error`.
- **Every failure behaviour** in skill `fieldtest-resilience` has a test.
- **Every hook and guard** has tests that pipe a sample payload in and assert the exit
  code and message (brief Phase 0A), plus its real-world bypasses.
- One runnable check per non-trivial unit. No suites for one-liners. Whole suite well
  under a minute.

## Pick the lightest form

1. **Doctest** for pure functions: it documents and tests at once.
2. **Unit test**, parametrized over edge cases: arrange, act, assert.
3. **Snapshot**: fixture in, exact bytes out, in `tests/snapshots/`. Regenerated only by
   an explicit flag, and the diff is reviewed. Required for `report.html` (brief §4.8).
4. **Determinism test**: run twice and compare bytes; run once more in a subprocess with a
   different `PYTHONHASHSEED`.

## Fixtures that pin the scorers (Phase 1)

- **Perfect predictor** (gold as predictions): 100% accuracy, 0% unsafe.
- **Empty predictor**: 0% accuracy, 100% abstention.
- **One crafted fixture per outcome**: `correct`, `missing`, `wrong`, `hallucinated`,
  `invalid`, `call_failed`, each asserted by name.
- **Gold validator**: a label whose evidence quote doesn't match the text at its offsets,
  a non-null label without evidence, and a quote that doesn't normalize to the value each
  fail validation.
- **Recommendation**: the cheapest model qualifies; only the large one qualifies;
  `NOT_READY` with its blocking fields; a tie broken by model ID (Phase 3).

## LLM behaviour: replay, never live

LLM tests run in `replay` mode against fixtures under `tests/fixtures/llm/` (or the
committed demo cache). A replay miss must raise, and a test proves it. Provider
response shapes come from recorded cassettes; fakes are in-process stubs. A live call
belongs in `scripts/smoke_llm.py`, outside the suite.

## Fault injection

A fake transport returning 429 then 200 (retried); 401 (fails at once); a budget spent
mid-run (the rest fail fast, recorded); a never-replying fake (the timeout trips); a
broken document (`item_failed`, the run completes); a crash between temp write and
rename (no visible artifact, the rerun completes); a second concurrent run (refused).

## Where tests live

`tests/` mirrors `src/fieldtest/`; `tests/hooks/` and `tests/scripts/` cover the hooks
and guards; `tests/test_public_repo.py` proves every publishable file passes the guard.
Shared fixtures are in `tests/conftest.py`. A fake secret, home path or personal
email is assembled from pieces at runtime, so no test source ever holds one.
