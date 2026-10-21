#!/usr/bin/env bash
# Drive the autonomous loop: one fresh headless Claude Code session per iteration, each
# running the `autopilot` skill (one PR, end to end), until the work needs a human.
#
# Usage: scripts/autopilot.sh [MAX_ITERATIONS]          (default 5)
#   FIELDTEST_AUTOPILOT_BUDGET_USD=20 caps each iteration's API spend (API billing only).
# Stop:  touch .autopilot/STOP   (checked before each iteration)
#
# Each iteration ends with one `AUTOPILOT-RESULT:` line (CLAUDE.md, The loop). The driver
# stops on anything but `merged`, after two failed iterations in a row, or at the cap.
# Never add --bare (it skips every hook) or --permission-mode bypassPermissions.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

max="${1:-5}"
mkdir -p .autopilot
budget=()
if [ -n "${FIELDTEST_AUTOPILOT_BUDGET_USD:-}" ]; then
  budget=(--max-budget-usd "$FIELDTEST_AUTOPILOT_BUDGET_USD")
fi

failures=0
for i in $(seq 1 "$max"); do
  if [ -e .autopilot/STOP ]; then
    echo "autopilot: .autopilot/STOP is present; stopping."
    exit 0
  fi
  open=$(gh issue list --label needs-human --state open --json number --jq length)
  if [ "$open" != "0" ]; then
    echo "autopilot: $open open needs-human issue(s); a human acts first."
    exit 0
  fi

  log=".autopilot/$(date -u +%Y%m%dT%H%M%SZ)-$i.log"
  echo "autopilot: iteration $i/$max (log: $log)"
  # ${budget[@]+...}: an empty array under `set -u` breaks macOS's bash 3.2 otherwise.
  if claude -p "/autopilot" --permission-mode auto ${budget[@]+"${budget[@]}"} >"$log" 2>&1; then
    failures=0
  else
    failures=$((failures + 1))
  fi

  result=$(grep -Eo 'AUTOPILOT-RESULT: [a-z-]+.*' "$log" | tail -1 || true)
  echo "autopilot: ${result:-no result line}"
  case "$result" in
    "AUTOPILOT-RESULT: merged"*) continue ;;
    "") [ "$failures" -lt 2 ] && continue
        echo "autopilot: two iterations in a row ended without a result; stopping."
        exit 1 ;;
    *) exit 0 ;;
  esac
done
echo "autopilot: reached $max iterations."
