---
name: fieldtest-resilience
description: >
  Failure design for the fieldtest run pipeline (brief §3.8: "it's still a distributed
  system"): failure classes, rate limiting, retries with backoff inside a budget,
  timeouts, per-item isolation, typed failures in the ledger, idempotent reruns,
  atomic writes and run locks. Read this BEFORE writing code that calls a model
  provider or the network, writes outside a run directory, or runs a multi-item stage.
---

# fieldtest-resilience

Design every stage for the day it fails halfway. Ask: what state is left behind, can a
rerun finish without doing work twice, and does the report say what failed?

## Classify every failure

| Class | Examples | Behaviour |
|---|---|---|
| **Transient** | 429, 5xx, connection reset, timeout | Retry with capped exponential backoff and jitter; honour `Retry-After`; give up after the item's attempts or the run's retry budget, then `call_failed` |
| **Permanent** | 400, 401, 403, unknown model ID | Fail at once with the cause. A 401 stops the run: every later call would fail too |
| **Data** | unreadable document, schema-invalid output, unnormalizable value | `item_failed` or `invalid` with a typed reason; the run continues |
| **Bug** | assertion, contract violation in the core | Fail loud with the traceback; no catch-all |

Catch specific exceptions. A bare `except Exception` is allowed only at a per-item
isolation boundary, and it records the item and the exception type.

## Rate limit and budget

- The client spaces requests by the configured rate (default 1/s for the free tier).
  The limiter is in the client, so every caller shares it.
- Per call: a timeout well below the SDK default, and a fixed number of attempts.
- Per run: a retry budget from config. Once it's spent, the remaining calls fail fast as
  `call_failed` (recorded), so a provider outage can't stretch a run without end.
- A cache hit costs nothing and never touches the limiter.

## Isolate items, not stages

One poisoned document never blocks a run (brief §3.8). Each item is processed inside
its own boundary. Its failure becomes a ledger event (`item_failed`, typed reason) and
a count in `results.json`. The run fails as a whole only on a bug or a permanent error
that would fail every item (bad credentials, unknown model).

## Idempotent and resumable

- **State comes from the ledger** (brief §3.7). A rerun reads `ledger.jsonl`, skips
  items whose terminal event exists, and converges to a no-op.
- **Deterministic run IDs** from the manifest inputs' hash, never random.
- **Atomic writes:** write `path.tmp-<pid>` in the same directory, `fsync`, then
  `os.replace`. Ledger appends are single `write` calls of one line each, flushed.
- **Cache entries** are written atomically, with the key's inputs stored beside the
  response. A corrupt or mismatched entry is a miss (an error in `replay`).
- **One writer per run:** a lock file (`runs/<run_id>/.lock`, created with `O_EXCL`,
  holding the pid). A stale lock is reported, never broken silently.

## Observability

The ledger is the operational record: every call (`llm_called`, cache hit or miss,
attempts, latency), every failure with its reason, and the run's counts. The report puts
failures first: a run with failures says so at the top.

## Tests for failure paths

Each behaviour above has a test (skill `fieldtest-tests`, Fault injection): a 429 then a
200 is retried and succeeds; a 401 fails on the first attempt; a spent budget fails the
rest fast and records them; a broken document becomes `item_failed` and the run
completes; a crash between temp write and rename leaves no visible artifact; a rerun
is a no-op; a second concurrent run is refused by the lock.
