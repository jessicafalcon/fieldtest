#!/usr/bin/env python3
"""Render the loop's sandbox settings for one driver session (ADRs 0005, 0006). Stdlib only.

  python3 -I scripts/render_sandbox.py ROOT > .autopilot/sandbox.json

Replaces `{ROOT}` in `.claude/sandbox.autopilot.json` with the repo's absolute path (relative
sandbox paths would resolve against the settings file), then denies the loop every write
to code that later runs outside the sandbox: each guardrail path (hooks, guard, driver,
preflight), `.venv`, `.git/hooks`, `.git/config` and the trusted tool caches. The denial is
both a sandbox `denyWrite` (shell commands) and an `Edit` permission rule (the file tools,
which run outside the sandbox).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parent))
from guard_rules import GUARDRAIL_PATHS

# Run outside the sandbox later: by the driver, the hooks, git, or the owner's own commands.
EXECUTED_OUTSIDE = (".venv", ".git/hooks", ".git/config")
TRUSTED_CACHES = ("~/.cache/uv", "~/.cache/pre-commit")


def render(template: str, root: Path) -> dict[str, Any]:
    """The session's settings: the template for `root`, plus the write and edit denials."""
    settings = json.loads(template.replace("{ROOT}", str(root)))
    repo_paths = [str(root / p.rstrip("/")) for p in (*GUARDRAIL_PATHS, *EXECUTED_OUTSIDE)]
    sandbox_fs = settings["sandbox"]["filesystem"]
    sandbox_fs["denyWrite"] = [*repo_paths, *TRUSTED_CACHES]
    # Permission rules spell an absolute path with `//`; a directory covers its contents.
    edit_rules = [
        f"Edit(/{path}/**)" if (root / rel).is_dir() or rel.endswith("/") else f"Edit(/{path})"
        for rel, path in zip((*GUARDRAIL_PATHS, *EXECUTED_OUTSIDE), repo_paths, strict=True)
    ]
    edit_rules += [f"Edit({cache}/**)" for cache in TRUSTED_CACHES]
    settings["permissions"]["deny"] = [*settings["permissions"]["deny"], *edit_rules]
    return settings


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(argv[0]).resolve()
    template = (root / ".claude" / "sandbox.autopilot.json").read_text(encoding="utf-8")
    print(json.dumps(render(template, root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
