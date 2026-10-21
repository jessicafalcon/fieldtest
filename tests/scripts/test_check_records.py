"""The records check catches tooling CLAUDE.md doesn't name and a README behind PROGRESS."""

from __future__ import annotations

import json
from pathlib import Path

from check_records import problems

from tests.conftest import ROOT


def make_tree(root: Path, *, claude_md: str, readme_phase: str, settings_script: str) -> None:
    (root / ".claude" / "agents").mkdir(parents=True)
    (root / ".claude" / "skills" / "autopilot").mkdir(parents=True)
    (root / ".claude" / "hooks").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".claude" / "agents" / "merge-gate.md").write_text("---\nname: merge-gate\n---\n")
    (root / ".claude" / "skills" / "autopilot" / "SKILL.md").write_text(
        "---\nname: autopilot\n---\n"
    )
    (root / ".claude" / "hooks" / "bash_policy.py").write_text("")
    command = f'python3 "$CLAUDE_PROJECT_DIR/{settings_script}"'
    settings = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]}}
    (root / ".claude" / "settings.json").write_text(json.dumps(settings))
    (root / "CLAUDE.md").write_text(claude_md)
    (root / "README.md").write_text(f"**Current phase:** {readme_phase}\n")
    (root / "docs" / "PROGRESS.md").write_text("- **Current phase:** 0A — tooling\n")


def test_consistent_records_pass(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        claude_md="`merge-gate` `autopilot` `bash_policy.py`",
        readme_phase="0A — tooling",
        settings_script=".claude/hooks/bash_policy.py",
    )
    assert problems(tmp_path) == []


def test_every_drift_is_reported(tmp_path: Path) -> None:
    make_tree(
        tmp_path,
        claude_md="`merge-gate`",
        readme_phase="0B",
        settings_script=".claude/hooks/gone.py",
    )
    found = problems(tmp_path)
    assert any("`autopilot`" in p for p in found)
    assert any("`bash_policy.py`" in p for p in found)
    assert any("gone.py" in p for p in found)
    assert any("current phase" in p for p in found)


def test_this_repo_records_agree() -> None:
    assert problems(ROOT) == []
