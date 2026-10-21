"""The session-context and format hooks: helpful when they can be, never blocking."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.conftest import ROOT

HOOKS = ROOT / ".claude" / "hooks"


def run(script: str, root: Path, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=stdin,
        text=True,
        capture_output=True,
        env={"CLAUDE_PROJECT_DIR": str(root), "PATH": "/usr/bin:/bin"},
        check=False,
    )


def test_session_context_prints_the_status_block_and_the_contract(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PROGRESS.md").write_text(
        "# Progress\n<!-- status:start -->\n- **Current phase:** 1\n<!-- status:end -->\nlog\n"
    )
    result = run("session_context.py", tmp_path)
    assert result.returncode == 0
    assert "- **Current phase:** 1" in result.stdout
    assert "log" not in result.stdout
    assert "Determinism contract" in result.stdout


def test_session_context_never_blocks_without_a_progress_file(tmp_path: Path) -> None:
    result = run("session_context.py", tmp_path)
    assert result.returncode == 0
    assert "no status block" in result.stdout


def test_format_hook_ignores_non_python_files(tmp_path: Path) -> None:
    note = tmp_path / "a.md"
    note.write_text("x\n")
    result = run("format_python.py", tmp_path, json.dumps({"tool_input": {"file_path": str(note)}}))
    assert (result.returncode, result.stdout) == (0, "")


def test_format_hook_formats_and_reports_what_ruff_cannot_fix(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "ruff").symlink_to(ROOT / ".venv" / "bin" / "ruff")
    source = tmp_path / "a.py"
    source.write_text("x = ( 1 )\ny = undefined_name\n")
    result = run(
        "format_python.py", tmp_path, json.dumps({"tool_input": {"file_path": str(source)}})
    )
    assert result.returncode == 0
    assert source.read_text().startswith("x = 1\n")
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "F821" in context
