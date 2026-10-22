#!/usr/bin/env python3
"""PreToolUse on Read/Edit/Write: deny files Claude must never read or write. Stdlib only.

Never read: `.env` and `.env.*` (except `.env.example`), `.private/**`, and
`.autopilot/gh/**` (the loop's short-lived token). Never written, additionally:

- `.env` and `.env.*` (except `.env.example`), `.private/**`, `CLAUDE.local.md`: the
  human's secrets and private context.
- `cache/llm/**`: written only by the record/replay cache code, so every entry matches
  its key.
- `.git/**`: git's own state.
- An accepted decision record on `main` (`docs/adr/NNNN-*.md` that says
  `Status: Accepted`): never rewritten; a new record supersedes it.
- A `data/<usecase>/gold.jsonl` on `main`: labels change only through the labeling
  script under a new decision record, never by a hand edit.

- `.gitignore` without every line in `REQUIRED_IGNORES` (scripts/guard_rules.py): lines
  can be added, but the ones that keep `.env` and private context out of git never go.

The ADR and gold rules leave a file editable on the branch that introduces it, until it merges.

The brief's "ask" cases are denials here because the loop runs unattended: a prompt would
stall it, and every case has a deterministic route that doesn't need one.
Any crash exits 2, so a broken hook blocks instead of allowing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from guard_rules import missing_ignores


def read_reason(rel: str) -> str | None:
    """Why `rel` must not be read, or None."""
    p = PurePosixPath(rel)
    if (p.name == ".env" or p.name.startswith(".env.")) and p.name != ".env.example":
        return "environment files hold the keys; only the allowlisted commands load .env"
    if p.parts[:1] == (".private",):
        return "private context is the human's"
    if p.parts[:2] == (".autopilot", "gh"):
        return "it holds the loop's GitHub token"
    return None


def reason(rel: str, root: Path) -> str | None:
    """Why `rel` (repo-relative, POSIX) must not be written, or None."""
    p = PurePosixPath(rel)
    name = p.name
    if why := read_reason(rel):
        return why
    if name == "CLAUDE.local.md":
        return "personal context is the human's to write"
    if p.parts[:2] == ("cache", "llm"):
        return "cache/llm/ is written only by the cache code (`--cache record`)"
    if p.parts[:1] == (".git",):
        return ".git/ is git's own state"
    if re.fullmatch(r"docs/adr/\d{4}-.+\.md", rel) and not name.startswith("0000-"):
        merged = _on_main(root, rel)
        if merged is not None and re.search(r"(?im)^\**status:?\**:?\s*accepted", merged):
            return (
                "accepted decision records are never rewritten; write a new one that supersedes it"
            )
    if re.fullmatch(r"data/[^/]+/gold\.jsonl", rel) and _on_main(root, rel) is not None:
        return "gold labels on main change only through the labeling script under a new ADR"
    return None


def _on_main(root: Path, rel: str) -> str | None:
    """The file's text on `origin/main` (or local `main` before the first push), or None."""
    for ref in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "show", f"{ref}:{rel}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    return None


def gitignore_after(tool: str, tool_input: dict[str, Any], current: str) -> str:
    """The `.gitignore` text this Write, Edit or MultiEdit would leave."""
    if tool == "Write":
        return str(tool_input.get("content", ""))
    edits = tool_input.get("edits") or [tool_input]
    text = current
    for edit in edits:
        old, new = edit.get("old_string", ""), edit.get("new_string", "")
        text = text.replace(old, new) if edit.get("replace_all") else text.replace(old, new, 1)
    return text


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not raw:
        return 0
    try:
        rel = Path(raw).resolve().relative_to(root).as_posix()
    except ValueError:
        return 0  # outside the project: memory, scratchpad
    if tool == "Read":
        why = read_reason(rel)
        verb = "reading"
    else:
        why = reason(rel, root)
        verb = "writing"
        if why is None and rel == ".gitignore":
            current = (root / rel).read_text(encoding="utf-8") if (root / rel).is_file() else ""
            if lost := missing_ignores(gitignore_after(tool, tool_input, current)):
                why = f"it would drop the required lines {', '.join(lost)}"
    if why is None:
        return 0
    print(f"protect-files: blocked {verb} {rel}: {why}.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"protect-files: blocked, the hook failed: {error!r}", file=sys.stderr)
        sys.exit(2)
