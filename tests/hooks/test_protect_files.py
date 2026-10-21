"""Protected files are denied to Edit/Write; everything else in the repo is writable."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from protect_files import reason

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
