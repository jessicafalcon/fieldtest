#!/usr/bin/env bash
# One-time, human-run setup of the public GitHub repo: create it, push `main`, and turn
# on every server-side control the loop relies on (ADRs 0001–0003). Idempotent: a second
# run re-applies the settings. Run it as yourself (`gh auth login`, `repo` and `workflow`
# scopes), never under the loop's identity. Then install the loop's GitHub App on the
# repo (PROJECT-BRIEF.md §12, step 4).
#
# Usage: scripts/setup_github.sh OWNER/REPO
#
# The Claude Code bash policy blocks these calls inside a session on purpose: repository
# settings are human-owned. Run it yourself, or approve it once in the session that bootstraps
# the repo.
set -euo pipefail

repo="${1:?usage: scripts/setup_github.sh OWNER/REPO}"
cd "$(git rev-parse --show-toplevel)"

say() { printf '\n== %s\n' "$*"; }
try() { "$@" >/dev/null || echo "   (not applied: $*; set it in the repo settings by hand)"; }

say "Repository"
# The description opens with the question the tool answers. Keep in sync with the README.
description="Is an LLM good enough for your document task, which one, and at what cost? \
fieldtest runs your labeled documents through several models and reports accuracy, unsafe \
errors, cost per 1,000 documents and whether it can be self-hosted, reproducibly."
topics=(llm llm-evaluation model-selection document-extraction information-extraction
  structured-output evaluation reproducibility record-replay mistral ollama self-hosted
  python claude-code)
if ! gh repo view "$repo" >/dev/null 2>&1; then
  gh repo create "$repo" --public --source . --remote origin --description "$description"
fi
git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$repo.git"
gh repo edit "$repo" --description "$description"
for topic in "${topics[@]}"; do gh repo edit "$repo" --add-topic "$topic" >/dev/null; done

say "Push main (the one direct push; every later change arrives by PR)"
git push -u origin main

say "Merge settings: squash only, PR title as the commit, branches deleted on merge"
gh api -X PATCH "repos/$repo" --silent --input - <<'JSON'
{
  "has_wiki": false,
  "has_projects": false,
  "allow_squash_merge": true,
  "allow_merge_commit": false,
  "allow_rebase_merge": false,
  "allow_auto_merge": false,
  "delete_branch_on_merge": true,
  "squash_merge_commit_title": "PR_TITLE",
  "squash_merge_commit_message": "COMMIT_MESSAGES",
  "security_and_analysis": {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"}
  }
}
JSON

say "Dependabot alerts and security updates, private vulnerability reporting"
try gh api -X PUT "repos/$repo/vulnerability-alerts"
try gh api -X PUT "repos/$repo/automated-security-fixes"
try gh api -X PUT "repos/$repo/private-vulnerability-reporting"

say "Actions: read-only token, no PR approvals by workflows, approval for outside contributors"
try gh api -X PUT "repos/$repo/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false
try gh api -X PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=all_external_contributors
# Only GitHub-owned actions and the one third-party action CI uses, pinned by SHA.
try gh api -X PUT "repos/$repo/actions/permissions" --input - <<'JSON'
{"enabled": true, "allowed_actions": "selected", "sha_pinning_required": true}
JSON
try gh api -X PUT "repos/$repo/actions/permissions/selected-actions" --input - <<'JSON'
{"github_owned_allowed": true, "verified_allowed": false, "patterns_allowed": ["astral-sh/setup-uv@*"]}
JSON

say "The label the loop uses to call you"
gh label create needs-human --repo "$repo" --color B60205 --force \
  --description "The autonomous loop stopped: a human must act (see the issue)"

say "Ruleset on main: PR only, squash, linear, no force push or deletion, CI must pass"
# integration_id 15368 is GitHub Actions, so only a real CI run can satisfy the checks.
# A change to a CODEOWNERS path (every guardrail) needs the owner's approval, and a push
# after it dismisses it, so GitHub itself enforces the approval (ADR 0006). The loop's App
# authors its PRs and can never approve them. No bypass actors: not even an admin skips this.
ruleset=$(cat <<'JSON'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": true,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["squash"]}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "do_not_enforce_on_create": false,
      "required_status_checks": [
        {"context": "check", "integration_id": 15368},
        {"context": "security", "integration_id": 15368}]}}
  ]
}
JSON
)
existing=$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name == "main") | .id')
if [ -n "$existing" ]; then
  gh api -X PUT "repos/$repo/rulesets/$existing" --silent --input - <<<"$ruleset"
else
  gh api -X POST "repos/$repo/rulesets" --silent --input - <<<"$ruleset"
fi

say "Done. Verify: gh api repos/$repo/rulesets; gh repo view $repo --json visibility,description"
echo "Next: install the loop's GitHub App on $repo (PROJECT-BRIEF.md §12, step 4)."
