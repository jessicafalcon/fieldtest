"""Protected files are denied to Edit/Write; everything else in the repo is writable."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from protect_files import read_reason, reason

from tests.conftest import ROOT, git

HOOK = ROOT / ".claude" / "hooks" / "protect_files.py"


@pytest.mark.parametrize(
    "rel",
    [
        ".env",
        ".env.local",
        ".private/denylist.txt",
        "CLAUDE.local.md",
        "cache/llm/0a1b2c.json",
        ".git/config",
    ],
)
def test_secret_private_cache_and_git_paths_are_denied(rel: str, repo: Path) -> None:
    assert reason(rel, repo) is not None


@pytest.mark.parametrize(
    "rel", [".env.example", "README.md", "cache/README.md", "docs/adr/0000-template.md"]
)
def test_ordinary_paths_are_writable(rel: str, repo: Path) -> None:
    assert reason(rel, repo) is None


def commit_on(repo: Path, branch: str, rel: str, text: str) -> None:
    git(repo, "switch", "-q", "-C", branch)
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", f"docs: add {rel}")


def test_an_accepted_adr_is_editable_on_its_branch_and_frozen_once_on_main(repo: Path) -> None:
    rel = "docs/adr/0003-x.md"
    commit_on(repo, "docs/x", rel, "# 0003\n\n**Status:** Accepted\n")
    assert reason(rel, repo) is None  # still under review on its branch
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "docs/x")
    assert reason(rel, repo) is not None
    assert reason("docs/adr/0004-new.md", repo) is None  # a new record supersedes it


def test_a_proposed_adr_on_main_stays_editable(repo: Path) -> None:
    commit_on(repo, "main", "docs/adr/0005-y.md", "# 0005\n\nStatus: Proposed\n")
    assert reason("docs/adr/0005-y.md", repo) is None


def test_gold_labels_are_frozen_once_on_main(repo: Path) -> None:
    rel = "data/tenders/gold.jsonl"
    assert reason(rel, repo) is None  # drafting the first set
    commit_on(repo, "main", rel, "{}\n")
    assert reason(rel, repo) is not None


@pytest.mark.parametrize(
    ("rel", "blocked"),
    [
        (".env", True),
        (".env.local", True),
        (".private/notes.md", True),
        (".autopilot/gh/hosts.yml", True),
        (".env.example", False),
        ("CLAUDE.local.md", False),  # read and followed (brief §11.1), never written
        ("cache/llm/ab.json", False),
    ],
)
def test_reads_of_keys_private_context_and_the_loop_token_are_denied(
    rel: str, blocked: bool
) -> None:
    assert (read_reason(rel) is not None) is blocked


REQUIRED = ".env\n.env.*\n!.env.example\n.private/\nCLAUDE.local.md\n.autopilot/\n"


@pytest.mark.parametrize(
    ("tool", "tool_input", "blocked"),
    [
        ("Write", {"content": REQUIRED + "runs/\n"}, False),
        ("Write", {"content": "runs/\n"}, True),
        ("Edit", {"old_string": "runs/\n", "new_string": "runs/\ndist/\n"}, False),
        ("Edit", {"old_string": ".env\n", "new_string": ""}, True),
        ("MultiEdit", {"edits": [{"old_string": "!.env.example\n", "new_string": ""}]}, True),
    ],
)
def test_gitignore_edits_keep_the_required_lines(
    repo: Path, tool: str, tool_input: dict[str, Any], blocked: bool
) -> None:
    (repo / ".gitignore").write_text(REQUIRED + "runs/\n")
    payload = {
        "tool_name": tool,
        "tool_input": {"file_path": str(repo / ".gitignore"), **tool_input},
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env={"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert (result.returncode == 2) is blocked, result.stderr


def test_hook_exits_2_on_a_cache_edit_and_0_outside_the_repo(repo: Path, tmp_path: Path) -> None:
    def run(file_path: Path) -> int:
        payload = json.dumps({"tool_input": {"file_path": str(file_path)}})
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=payload,
            text=True,
            capture_output=True,
            env={"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"},
            check=False,
        ).returncode

    assert run(repo / "cache" / "llm" / "ab.json") == 2  # the brief's Phase 0A acceptance case
    assert run(repo / "src" / "x.py") == 0
    assert run(tmp_path / "elsewhere.txt") == 0


def run_hook(repo: Path, tool: str, tool_input: dict[str, Any], *, driver: bool) -> int:
    env = {"CLAUDE_PROJECT_DIR": str(repo), "PATH": "/usr/bin:/bin"}
    if driver:
        env["FIELDTEST_DRIVER"] = "1"
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    ).returncode


@pytest.mark.parametrize(
    "rel",
    [
        "scripts/guard.py",
        ".claude/hooks/x.py",
        ".claude/agents/plan-arbiter.md",
        "pyproject.toml",
        ".venv/lib/python3.12/site-packages/evil.pth",
        ".git/hooks/pre-push",
    ],
)
def test_under_the_driver_code_that_runs_outside_the_sandbox_is_unwritable(
    repo: Path, rel: str
) -> None:
    target = {"file_path": str(repo / rel), "content": "x"}
    assert run_hook(repo, "Write", target, driver=True) == 2
    if not rel.startswith((".venv", ".git")):
        assert run_hook(repo, "Write", target, driver=False) == 0  # the owner's session may


def test_under_the_driver_only_temp_dirs_are_writable_outside_the_project(repo: Path) -> None:
    home_file = {"file_path": str(Path.home() / ".zshrc"), "content": "x"}
    assert run_hook(repo, "Write", home_file, driver=True) == 2
    scratch = {"file_path": "/tmp/scratch.txt", "content": "x"}  # noqa: S108 (never created)
    assert run_hook(repo, "Write", scratch, driver=True) == 0
    in_repo = {"file_path": str(repo / "src/x.py"), "content": "x"}
    assert run_hook(repo, "Write", in_repo, driver=True) == 0


def test_grep_and_glob_cannot_read_the_token_or_the_keys(repo: Path) -> None:
    assert (
        run_hook(
            repo, "Grep", {"pattern": "token", "path": str(repo / ".autopilot/gh")}, driver=False
        )
        == 2
    )
    assert (
        run_hook(repo, "Glob", {"pattern": "*", "path": str(repo / ".private")}, driver=False) == 2
    )
    assert run_hook(repo, "Grep", {"pattern": "x", "path": str(repo)}, driver=False) == 0
