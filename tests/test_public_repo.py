"""Every file that would be committed passes the public-repo guard, and the private ones are
ignored. This is the check that the repo is safe to publish as it stands."""

from __future__ import annotations

import subprocess

from guard_rules import forbidden_path, missing_ignores, scan_text

from tests.conftest import ROOT


def publishable_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.splitlines() if (ROOT / p).is_file())


def test_no_publishable_file_is_private() -> None:
    assert [p for p in publishable_files() if forbidden_path(p)] == []


def test_no_publishable_file_holds_a_secret_or_personal_data() -> None:
    findings = []
    for path in publishable_files():
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        findings += scan_text(text, path, [], path=path)
    assert findings == []


def test_private_paths_are_gitignored() -> None:
    probes = [".private/x", ".env", ".env.local", "CLAUDE.local.md", ".claude/settings.local.json"]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *probes],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sorted(result.stdout.split()) == sorted(probes)


def test_gitignore_keeps_every_required_line() -> None:
    assert missing_ignores((ROOT / ".gitignore").read_text(encoding="utf-8")) == []
