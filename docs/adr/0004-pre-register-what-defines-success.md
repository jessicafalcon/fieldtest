# 0004. Pre-register what defines success, and let the owner alone change it

Status: Accepted
Date: 2026-10-22

## Context and Problem Statement

fieldtest's output is a verdict: a model is ready for a use case, or it isn't. The
verdict is only as honest as what it's measured against: the fields, the thresholds, the
gold labels, the model list and prices, the outcome taxonomy, the recommendation rule, and
each phase's acceptance criteria. The loop builds and merges on its own (ADR 0001). The
arbiter's policy says such changes go to the human, but nothing enforced it: none of these
files needed approval, and nor did the files that define the loop's own authority (the
arbiter's policy, the autopilot skill, the reviewer agents). A loop under pressure to reach
a result could relax `max_unsafe_rate` after seeing the scores, or soften the rule that would
have escalated that change, and merge it with only its own agents' review.

## Considered Options

1. **Trust the arbiter's policy.** It's an instruction, and it's editable by the loop.
2. **Make every such file a guardrail.** The owner then approves all eval-design work in
   Phases 1–3, PR by PR, while it's still being shaped.
3. **Pre-register.** The design stays open while it's being built, and freezes at Phase 1's
   exit with one approval. After that, every change needs the owner. The documents that
   define authority and success are guarded at all times.

## Decision Outcome

Chosen option: **3**, because it puts the human on exactly the decisions that could bias a
result. It costs one sign-off per project, plus one per deviation.

- `config/preregistration.json` lists the frozen paths (`usecases/`, the gold labels and
  their `DATASET.md`, `config/models.yaml`). It is a guardrail. Phase 1's exit PR sets
  `"frozen": true`, so the owner's approval of that PR signs off the evaluation design.
  Once main says frozen, a PR touching a listed path needs the owner's approving review on
  its head.
- **Guarded regions.** Text between `<!-- guarded:start -->` and `<!-- guarded:end -->`
  on main changes only with the same approval. The brief guards §3, §4 (including
  pre-registration and text-grounded gold), the outcome taxonomy and recommendation rule,
  every acceptance criterion, and the escalation, identity, keys and sandbox policy;
  `CLAUDE.md` guards the matching sections. The guard maps each hunk to main's line numbers.
  Unpaired markers guard the whole file, so a broken marker never opens one.
- **Authority files** become guardrails: every agent, and the skills `autopilot`,
  `phase-start`, `phase-review`, `determinism-contract` and `fieldtest-security`.
- A change after the freeze also needs an ADR, and the findings list it under "Deviations
  from pre-registration".

### Consequences

- Good, because the loop can't move the goalposts, or rewrite the rules that would have
  stopped it, without the owner seeing the change.
- Good, because the result can say what was fixed in advance, and show it.
- Bad, because a genuine correction after the freeze, such as a mislabeled gold item,
  waits for the owner. That is intended: it's the case most likely to bias a result.
- Bad, because guarded markers add noise to two documents, and edits next to a region
  need care. The guard only counts lines inside a region, never the lines around it.
