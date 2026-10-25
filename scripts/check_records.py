#!/usr/bin/env python3
"""Check that the records agree with the repo. Stdlib only; runs in pre-commit and CI.

- CLAUDE.md names every agent, skill and hook script under `.claude/`.
- Every hook command in `.claude/settings.json` points at a file that exists.
- README.md and docs/PROGRESS.md state the same current phase.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PHASE = re.compile(r"\*\*Current phase:\*\*\s*(?P<phase>.+)")


def current_phase(text: str) -> str | None:
    """The phase named on the `**Current phase:**` line.

    >>> current_phase("- **Current phase:** 0A — tooling\\n")
    '0A — tooling'
    """
    match = PHASE.search(text)
    return match.group("phase").strip() if match else None


def problems(root: Path) -> list[str]:
    found: list[str] = []
    claude_md = (root / "CLAUDE.md").read_text(encoding="utf-8")

    names = [p.stem for p in sorted((root / ".claude" / "agents").glob("*.md"))]
    names += [p.parent.name for p in sorted((root / ".claude" / "skills").glob("*/SKILL.md"))]
    names += [p.name for p in sorted((root / ".claude" / "hooks").glob("*.py"))]
    found += [f"CLAUDE.md does not mention `{n}`" for n in names if f"`{n}`" not in claude_md]

    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                for script in re.findall(
                    r"\$CLAUDE_PROJECT_DIR/([\w./-]+)", hook.get("command", "")
                ):
                    if not (root / script).is_file():
                        found.append(f".claude/settings.json runs {script}, which does not exist")

    readme = current_phase((root / "README.md").read_text(encoding="utf-8"))
    progress = current_phase((root / "docs" / "PROGRESS.md").read_text(encoding="utf-8"))
    if progress is None:
        found.append("docs/PROGRESS.md has no `**Current phase:**` line")
    elif readme != progress:
        found.append(
            f"README.md says the current phase is {readme!r}; docs/PROGRESS.md says {progress!r}"
        )
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    found = problems(root)
    for problem in found:
        print(f"records: {problem}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
