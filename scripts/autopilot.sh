#!/usr/bin/env bash
# Drive the autonomous loop: one fresh headless Claude Code session per iteration, each
# running the `autopilot` skill (one PR, end to end), acting as the loop's own GitHub App.
#
# Usage: scripts/autopilot.sh [MAX_ITERATIONS]          (default 5)
#   FIELDTEST_AUTOPILOT_BUDGET_USD=20   caps each iteration's API spend (API billing only)
#   FIELDTEST_AUTOPILOT_WAIT_HOURS=24   how long to wait for you when the loop needs you
# Stop:  touch .autopilot/STOP   (checked before each iteration and while waiting)
#
# Identity (ADR 0003): every gh and git call in the session acts as the App, through a
# private gh config in .autopilot/gh/ that holds a one-hour token, refreshed every 30
# minutes and deleted on exit. The App's keys stay in .env; nothing here prints them.
#
# Sandbox (ADRs 0005, 0006): every shell command the session runs is confined by
# .claude/sandbox.autopilot.json, rendered by scripts/render_sandbox.py: no reads of .env, .private/ or your own credentials,
# network only to the allowlisted hosts, and MISTRAL_API_KEY visible only as a placeholder
# that the sandbox proxy replaces on requests to api.mistral.ai.
#
# Each iteration ends with one `AUTOPILOT-RESULT:` line (CLAUDE.md, The loop). After
# `merged` it continues; after `escalated`, `blocked` or `awaiting-approval` it waits for
# you (an issue closed, a PR approved) and then continues; after `done`, `error` (the loop
# can't operate and can't open an issue), or two failed iterations in a row, it stops. Never add --bare (it skips every hook) or
# --permission-mode bypassPermissions.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
root="$PWD"

max="${1:-5}"
wait_hours="${FIELDTEST_AUTOPILOT_WAIT_HOURS:-24}"
mkdir -p .autopilot
budget=()
if [ -n "${FIELDTEST_AUTOPILOT_BUDGET_USD:-}" ]; then
  budget=(--max-budget-usd "$FIELDTEST_AUTOPILOT_BUDGET_USD")
fi

# Trusted tooling (ADR 0006). The sandbox can't write `.venv`, `.git/hooks` or the uv and
# pre-commit caches, so only this driver, outside the sandbox, installs them: from the
# lockfile, through the trusted cache. Everything the driver itself runs uses that venv's
# interpreter in isolated mode (-I), so no file the loop wrote can change what it imports.
uv sync --frozen --quiet
uv run --frozen --no-sync pre-commit install-hooks >/dev/null
py=("$root/.venv/bin/python" -I)

# The loop's identity, from .github/loop-identity.json.
read -r login email < <("${py[@]}" -c 'import json; d = json.load(open(".github/loop-identity.json")); print(d["bot_login"], d["bot_email"])')
gh_bin="$(command -v gh)"
ghdir="$root/.autopilot/gh"
refresh() { "${py[@]}" scripts/loop_auth.py write-gh-config "$ghdir"; }
refresh
( while sleep 1800; do refresh || echo "autopilot: token refresh failed; retrying in 30 minutes" >&2; done ) &
refresher=$!
disown "$refresher"  # stopped by the exit trap, without a job-control notice
trap 'kill "$refresher" 2>/dev/null || true; rm -rf "$ghdir"' EXIT

export GH_CONFIG_DIR="$ghdir" GH_PROMPT_DISABLED=1 FIELDTEST_DRIVER=1
# Git asks only the App's credential: the empty value drops every other helper (such as
# the keychain holding your own token) for this process tree.
export GIT_CONFIG_COUNT=2 \
  GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= \
  GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1="!$gh_bin auth git-credential"
export GIT_AUTHOR_NAME="$login" GIT_AUTHOR_EMAIL="$email" \
  GIT_COMMITTER_NAME="$login" GIT_COMMITTER_EMAIL="$email"
echo "autopilot: acting as $login"

sandbox="$root/.autopilot/sandbox.json"

# Before each session: prerequisites (a key added while waiting is picked up), the sandbox
# settings, and the model key. The session can't read .env, so it reads the preflight report
# instead (no values).
prepare_session() {
  # FIELDTEST_DRIVER=0: the real check, not the report a session reads.
  if ! FIELDTEST_DRIVER=0 "${py[@]}" scripts/preflight.py --online | tee .autopilot/preflight.txt; then
    echo "autopilot: prerequisites missing (above); see PROJECT-BRIEF.md §12."
    return 1
  fi
  "${py[@]}" scripts/render_sandbox.py "$root" >"$sandbox"
  # The model key, if set, enters the session only here; sandboxed commands see it masked.
  model_key="$("${py[@]}" -c 'import sys; sys.path.append("scripts"); from pathlib import Path; from loop_auth import read_env; print(read_env(Path(".env")).get("MISTRAL_API_KEY", ""))')"
  if [ "$(git branch --show-current)" = main ] && [ -z "$(git status --porcelain)" ]; then
    git pull --quiet --ff-only  # guardrail files changed on main can't be written from inside
  fi
}

# Seconds until a Claude usage limit named in the log resets ("resets 3:10pm (Europe/Paris)"),
# or nothing when the session didn't hit one.
limit_wait() {
  "${py[@]}" - "$1" <<'PY'
import re, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
m = re.search(r"hit your (?:session|usage|weekly) limit.*?resets (\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(([^)]+)\)", text, re.I | re.S)
if m:
    hour, minute, ampm, zone = int(m[1]) % 12 + (12 if m[3].lower() == "pm" else 0), int(m[2] or 0), m[3], m[4]
    now = datetime.now(ZoneInfo(zone))
    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    print(int((reset - now).total_seconds()) + 120)
PY
}

# Wait while the loop needs you: an open needs-human issue, or a PR awaiting your approval.
wait_for_human() {
  local pr="$1" deadline=$(( $(date +%s) + wait_hours * 3600 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    [ -e .autopilot/STOP ] && return 1
    open=$(gh issue list --label needs-human --state open --json number --jq length)
    if [ "$open" = "0" ]; then
      if [ -z "$pr" ] || "${py[@]}" scripts/guard.py --approved "$pr" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 600
  done
  echo "autopilot: waited $wait_hours hours for you; stopping."
  return 1
}

failures=0
for i in $(seq 1 "$max"); do
  [ -e .autopilot/STOP ] && { echo "autopilot: .autopilot/STOP is present; stopping."; exit 0; }
  wait_for_human "" || exit 0
  prepare_session || exit 1

  log=".autopilot/$(date -u +%Y%m%dT%H%M%SZ)-$i.log"
  echo "autopilot: iteration $i/$max (log: $log)"
  # The session gets its own uv cache, so nothing it writes there reaches the trusted one.
  # ${budget[@]+...}: an empty array under `set -u` breaks macOS's bash 3.2 otherwise.
  if MISTRAL_API_KEY="$model_key" UV_CACHE_DIR="$root/.autopilot/uv-cache" \
      claude -p "/autopilot" --model claude-opus-5-5 --permission-mode auto \
      --settings "$sandbox" ${budget[@]+"${budget[@]}"} >"$log" 2>&1; then
    failures=0
  else
    failures=$((failures + 1))
  fi

  result=$(grep -Eo 'AUTOPILOT-RESULT: [a-z-]+.*' "$log" | tail -1 || true)
  echo "autopilot: ${result:-no result line}"
  if [ -z "$result" ] && wait_s="$(limit_wait "$log")" && [ -n "$wait_s" ]; then
    echo "autopilot: Claude usage limit reached; waiting $((wait_s / 60)) minutes for the reset."
    sleep "$wait_s"
    failures=0
    continue
  fi
  case "$result" in
    "AUTOPILOT-RESULT: merged"*) continue ;;
    "AUTOPILOT-RESULT: awaiting-approval #"*)
      wait_for_human "${result##*#}" || exit 0 ;;
    "AUTOPILOT-RESULT: escalated"* | "AUTOPILOT-RESULT: blocked"*)
      wait_for_human "" || exit 0 ;;
    "AUTOPILOT-RESULT: done"*) exit 0 ;;
    "AUTOPILOT-RESULT: error"*)
      echo "autopilot: the loop can't operate (above, and in $log); fix it, then rerun."
      exit 1 ;;
    *) if [ "$failures" -ge 2 ]; then
         echo "autopilot: two iterations in a row ended without a result; stopping."
         exit 1
       fi ;;
  esac
done
echo "autopilot: reached $max iterations."
