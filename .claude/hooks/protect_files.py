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

Under the loop's driver (`FIELDTEST_DRIVER=1`, ADR 0006), also denied: writing any guardrail
path, `.venv/` or `.git/` (code that runs outside the sandbox later), and writing anywhere
outside the project except temporary directories. The file tools run outside the sandbox,
so this hook is what keeps them inside the same boundary. Grep and Glob are checked like
Read, so a search can't read what a Read can't.

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

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))
from guard_rules import is_guardrail_path, missing_ignores


def read_reason(rel: str) -> str | None:
    """Why `rel` must not be read, or None."""
    p = PurePosixPath(rel)
    if (p.name == ".env" or p.name.startswith(".env.")) and p.name != ".env.example":
        return "environment files hold the keys; only the driver reads .env (ADR 0005)"
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


# Prefixes to compare paths against, not files this hook creates.
TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")  # noqa: S108
READ_TOOLS = {"Read", "Grep", "Glob"}


def driver_reason(rel: str) -> str | None:
    """Why the loop, under its driver, must not write `rel`, or None."""
    if is_guardrail_path(rel):
        return "a guardrail: the loop proposes the change in an issue, and the owner makes it"
    if rel.split("/", 1)[0] in {".venv", ".git"}:
        return "it holds code that runs outside the sandbox"
    return None


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    under_driver = os.environ.get("FIELDTEST_DRIVER") == "1"
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if tool in {"Grep", "Glob"}:
        raw = tool_input.get("path") or ""
    if not raw:
        return 0
    resolved = Path(raw).expanduser().resolve()
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        # Outside the project: the scratchpad, memory. Under the driver only temp dirs are
        # writable, so nothing it writes can land where something later executes it.
        if under_driver and tool not in READ_TOOLS and not str(resolved).startswith(TEMP_ROOTS):
            print(
                f"protect-files: blocked writing {resolved}: outside the project.", file=sys.stderr
            )
            return 2
        return 0
    if tool in READ_TOOLS:
        why = read_reason(rel) if rel != "." else None
        verb = "reading"
    else:
        why = reason(rel, root) or (driver_reason(rel) if under_driver else None)
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
