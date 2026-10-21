#!/usr/bin/env python3
"""SessionStart: put the current status and the determinism reminder in Claude's context.

Runs on startup, resume and after compaction, so the status survives a compact. Prints
the block between the status markers in docs/PROGRESS.md. Offline and stdlib only; never
blocks a session (exit 0 even when the file is missing).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REMINDER = """\
Determinism contract (PROJECT-BRIEF.md §4), always:
- Pinned, dated model IDs from config/models.yaml; temperature 0; JSON-schema output.
- Every LLM call goes through the record/replay cache; replay misses are errors; tests never touch the network.
- Validate, then normalize; unknown or malformed values become typed failures, never guesses.
- Sort by ID, JSON with sorted keys; wall-clock time only in manifest.json and ledger.jsonl.
- Reports render from results.json through Jinja2; no LLM writes report text."""

STATUS = re.compile(r"<!-- status:start -->\n(.*?)<!-- status:end -->", re.DOTALL)


def status_block(progress: str) -> str:
    """The text between the status markers, or a note that they are missing.

    >>> status_block("x\\n<!-- status:start -->\\n- **Current phase:** 0A\\n<!-- status:end -->\\n")
    '- **Current phase:** 0A'
    """
    match = STATUS.search(progress)
    return match.group(1).strip() if match else "(no status block in docs/PROGRESS.md)"


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    progress = root / "docs" / "PROGRESS.md"
    text = progress.read_text(encoding="utf-8") if progress.is_file() else ""
    print("fieldtest status (docs/PROGRESS.md):")
    print(status_block(text))
    print()
    print(
        "Before new work: `gh issue list --label needs-human --state open`. An open one means stop."
    )
    print()
    print(REMINDER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # context is a convenience; never block a session on it
        print(f"session-context: could not load status: {error!r}", file=sys.stderr)
        sys.exit(0)
