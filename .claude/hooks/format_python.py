#!/usr/bin/env python3
"""PostToolUse on Edit/Write: ruff-format and lint-fix an edited `.py` file. Stdlib only.

Non-blocking: lint that ruff can't fix comes back to Claude as additional context, so it
is fixed before the next edit. Quiet until ruff is installed. Config: pyproject.toml.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def ruff_command(root: Path) -> list[str] | None:
    # The venv binary first: `uv run` would re-sync the environment on every edit, which
    # is slow and can touch the network. `--no-sync` keeps the fallback read-only.
    venv_ruff = root / ".venv" / "bin" / "ruff"
    if venv_ruff.is_file():
        return [str(venv_ruff)]
    if shutil.which("uv"):
        return ["uv", "run", "--no-sync", "ruff"]
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    path = Path(file_path)
    if path.suffix != ".py" or not path.is_file():
        return 0
    if os.environ.get("FIELDTEST_DRIVER") == "1":
        # Under the loop's driver this hook would run `.venv` code outside the sandbox
        # (ADR 0006); pre-commit formats inside the sandbox at commit instead.
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    if not path.resolve().is_relative_to(root):
        return 0  # outside the project: the scratchpad, memory
    ruff = ruff_command(root)
    if ruff is None:
        return 0

    def run(*args: str) -> str:
        result = subprocess.run(
            [*ruff, *args, str(path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        return result.stdout

    run("format", "--quiet")
    # Keep unused imports (F401) mid-edit: stripping them breaks add-import-then-use
    # sequences. pre-commit still removes them before anything is committed.
    run("check", "--fix", "--unfixable", "F401", "--quiet")
    remaining = run("check", "--output-format", "concise", "--quiet").strip()
    if remaining:
        context = f"ruff: unresolved lint in {path.name}; fix it before the next edit:\n{remaining}"
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": context,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # formatting is a convenience; never fail the edit on it
        print(f"format-python: skipped: {error!r}", file=sys.stderr)
        sys.exit(0)
