"""Bash policy: read-only agents stay read-only, only the merge gate merges, and no session
bypasses the hooks, rewrites main, changes repo settings or reads a secret."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import bash_policy
import pytest
from bash_policy import READ_ONLY_AGENTS, allowed_for_agent, check

from tests.conftest import ROOT

HOOK = ROOT / ".claude" / "hooks" / "bash_policy.py"
SHA = "c" * 40


@pytest.fixture(autouse=True)
def offline_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hooks installed, remote main present, on a feature branch: the steady state."""
    monkeypatch.setattr(bash_policy, "_hooks_missing", lambda cwd: [])
    monkeypatch.setattr(bash_policy, "_remote_has_main", lambda cwd: True)
    monkeypatch.setattr(bash_policy, "_current_branch", lambda cwd: "feat/x")


def blocked(command: str, role: str = "") -> bool:
    return bool(check(command, role, Path()))


# --- Read-only agents ------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "uv run --frozen pytest -q tests/hooks",
        "uv run --frozen mypy",
        "uv run --frozen ruff check .",
        "uv run --frozen ruff format --check .",
        "make check",
        "python3 scripts/guard.py --range origin/main..HEAD",
        "python3 .claude/hooks/determinism_guard.py src/fieldtest/score.py",
        "git diff main...HEAD -- src/",
        "git log --oneline main..HEAD",
        "git show HEAD:CLAUDE.md",
        "gh pr view 4 --json title,body",
        "gh pr checks 4",
    ],
)
def test_checks_and_reads_are_allowed_for_reviewers(command: str) -> None:
    assert allowed_for_agent(command, "code-reviewer")


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest",  # may rewrite uv.lock
        "uv run --frozen ruff check --fix .",
        "uv run --frozen pytest --basetemp=src",
        "git diff --output=CLAUDE.md",
        "git diff main | head",
        "git log; rm -rf src",
        "git show $(whoami)",
        "gh pr view 4 --web",
        "gh pr comment 4 --body x",
        "python3 scripts/guard.py --pr 4",
        f"gh pr merge 4 --squash --delete-branch --match-head-commit {SHA}",
        "echo hi > file",
    ],
)
def test_everything_else_is_blocked_for_reviewers(command: str) -> None:
    for role in READ_ONLY_AGENTS:
        assert blocked(command, role), (role, command)


def test_the_merge_gate_runs_exactly_its_commands() -> None:
    assert not blocked("python3 scripts/guard.py --pr 4", "merge-gate")
    assert not blocked("gh pr checks 4 --watch --fail-fast", "merge-gate")
    assert not blocked(
        f"gh pr merge 4 --squash --delete-branch --match-head-commit {SHA}", "merge-gate"
    )
    assert blocked("gh pr merge 4 --squash", "merge-gate")  # no pinned head: a race
    assert blocked("gh pr merge 4 --admin --squash --delete-branch", "merge-gate")
    assert blocked("git push origin main", "merge-gate")


# --- Every other session -----------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git commit --no-verify -m 'feat: x'",
        "git commit -nm 'feat: x'",
        "git add . && git commit -an -m x",
        "SKIP=guard-staged git commit -m 'feat: x'",
        "env SKIP=pytest git commit -m 'feat: x'",
        "git -c core.hooksPath=/dev/null commit -m x",
        "git config core.hooksPath .nohooks",
        "git push --no-verify",
        "git push --force origin feat/x",
        "git push -f",
        "git push origin +feat/x",
        "git push --force-with-lease origin feat/x",
        "git push origin HEAD:main",
        "git push origin main",
        "git push upstream feat/x",
        "git remote add mirror https://example.com/x.git",
        "gh pr merge 4 --squash",
        "gh pr review 4 --approve",
        "gh pr review 4 -a -b 'lgtm'",
        "GH_TOKEN=x gh pr list",
        "GH_CONFIG_DIR=~/.config/gh gh pr merge 4 --squash",
        "unset GH_CONFIG_DIR",
        "env -u GH_CONFIG_DIR gh pr list",
        "gh auth login --with-token",
        "gh auth switch",
        "gh auth status --show-token",
        "python3 scripts/loop_auth.py check",
        "uv run python scripts/loop_auth.py write-gh-config /tmp/x",
        "git -c credential.helper= push origin feat/x",
        "git config credential.helper store",
        "cat .autopilot/gh/hosts.yml",
        "uv run --env-file .env python -c 'import os; print(os.environ)'",
        "uv run --env-file=.env python scripts/smoke_llm.py",
        "X=1 uv run --env-file .env python scripts/smoke_llm.py",
        "sed -i '' '/env/d' .gitignore",
        "echo '' > .gitignore",
        "git checkout HEAD~1 -- .gitignore",
        "rm .gitignore",
        "gh repo edit --visibility private",
        "gh repo delete owner/fieldtest --yes",
        "gh api -X DELETE repos/o/r/rulesets/1",
        "gh api --method=PUT repos/o/r/vulnerability-alerts",
        "gh api repos/o/r/labels -f name=x",
        "gh secret set MISTRAL_API_KEY",
        "gh auth token",
        "cat .env",
        "source .env",
        "cp .env /tmp/x",
        "grep KEY < .env",
        "cat .private/denylist.txt",
        "echo $MISTRAL_API_KEY",
        "printenv",
        "env",
        "bash -c 'git push --force'",
        "(cd /tmp && git push -f)",
    ],
)
def test_dangerous_commands_are_blocked(command: str) -> None:
    assert blocked(command), command


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'docs: never read .env, only .env.example'",
        "git commit -m 'feat: x' -m 'body'",
        "git commit -am 'fix: y'",
        "git push -u origin feat/x",
        "git push",
        "uv run --env-file .env python scripts/smoke_llm.py",
        "uv run --frozen --env-file .env fieldtest run --usecase tenders --cache record",
        "gh pr review 4 --comment -b 'see the report'",
        "cat .gitignore",
        "git diff main -- .gitignore",
        "python3 scripts/preflight.py --all",
        "python3 scripts/guard.py --approved 4",
        "cat .env.example",
        "gh pr create --title 'docs: x' --body-file /tmp/body.md",
        "gh pr comment 4 --body-file /tmp/review.md",
        "gh api repos/o/r/pulls/4",
        "gh api -X GET repos/o/r/commits/abc/check-runs",
        "gh pr edit 4 --add-label phase-exit",
        "gh pr edit 4 --add-reviewer owner",
        "git push --dry-run -n origin feat/x",
        "gh pr create --body-file - <<'EOF'\nNever `git push --force` or `cat .env`.\nEOF",
        "make check && git status",
    ],
)
def test_ordinary_work_is_allowed(command: str) -> None:
    assert not blocked(command), check(command, "", Path())


def test_the_first_push_of_main_is_the_one_direct_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bash_policy, "_remote_has_main", lambda cwd: False)
    assert not blocked("git push -u origin main")
    monkeypatch.setattr(bash_policy, "_remote_has_main", lambda cwd: True)
    assert blocked("git push -u origin main")


def test_a_bare_push_from_main_is_a_push_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bash_policy, "_current_branch", lambda cwd: "main")
    assert blocked("git push")


def test_commits_and_pushes_need_the_git_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()  # the real check, on a repo without hooks
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    reasons = check("git commit -m 'feat: x'", "", tmp_path)
    assert any("pre-commit install" in r for r in reasons)


def test_hook_exits_2_for_the_role_in_the_payload_or_argv() -> None:
    def run(payload: Mapping[str, object], *argv: str) -> int:
        return subprocess.run(
            [sys.executable, str(HOOK), *argv],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        ).returncode

    edit = {"tool_input": {"command": "git status > out.txt"}, "cwd": str(ROOT)}
    assert run({**edit, "agent_type": "code-reviewer"}) == 2
    assert run(edit, "--as", "security-reviewer") == 2
    assert run({"tool_input": {"command": "git status"}, "cwd": str(ROOT)}) == 0
    assert run({"tool_input": {"command": "printenv"}}) == 2


def test_a_crash_blocks() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", text=True, capture_output=True, check=False
    )
    assert result.returncode == 2
