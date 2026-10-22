"""Shared fixtures: throwaway git repos and samples that are built at runtime.

Fake secrets, home paths and personal emails are assembled from pieces, so this source
never contains one and the repo's own guard and gitleaks scan stay clean.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOREPLY = "1+tester@users.noreply.github.com"

FAKE_API_KEY = "sk-" + "ant-" + "Zq9" * 9
FAKE_GITHUB_TOKEN = "gh" + "p_" + "aB3" * 13
FAKE_ASSIGNMENT = "MISTRAL_API_KEY" + "=" + "q8Lw2" * 6
HOME_PATH = "/" + "Users" + "/someone/dev/x"
PERSONAL_EMAIL = "someone" + "@" + "gmail.com"


@pytest.fixture(autouse=True)
def _outside_the_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test as CI does: without the driver's flag or the App's git identity.

    `scripts/autopilot.sh` exports the App's author and committer and a `GIT_CONFIG_*`
    block; git lets them override a test repo's own config, so they are removed here.
    """
    for name in list(os.environ):
        if name == "FIELDTEST_DRIVER" or name.startswith(
            ("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG_")
        ):
            monkeypatch.delenv(name)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An empty git repo with a noreply identity and one commit on main."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "tester")
    git(path, "config", "user.email", NOREPLY)
    git(path, "config", "commit.gpgsign", "false")
    (path / "README.md").write_text("# test\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "chore: start")
    return path
