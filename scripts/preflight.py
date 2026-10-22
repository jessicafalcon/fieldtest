#!/usr/bin/env python3
"""Check the human prerequisites (PROJECT-BRIEF.md §12) without printing a secret.

  python3 scripts/preflight.py            the phases up to the current one (docs/PROGRESS.md)
  python3 scripts/preflight.py --all      every phase: the checklist before kickoff
  uv run --frozen python scripts/preflight.py --online   also mint a token as the loop's App

For `.env` it reports only whether each key is set. Exits 1 when a needed check fails.
The loop runs it before each iteration and escalates the failures it can't fix.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from loop_auth import APP_KEYS, read_env

ROOT = Path(__file__).resolve().parents[1]
# Written by scripts/autopilot.sh before each session, where .env is still readable.
DRIVER_REPORT = ROOT / ".autopilot" / "preflight.txt"
# Keep in sync with the phase list in PROJECT-BRIEF.md §7 and the table in §12.
PHASES = ("0A", "0B", "1", "2", "3", "3b", "4", "5a", "5b", "6", "7")


@dataclass(frozen=True)
class Result:
    name: str
    phase: str  # the first phase that needs it
    ok: bool | None  # None: a warning, never blocking
    detail: str
    fix: str  # the §12 step that sets it up


def run(*args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(
            args, cwd=ROOT, capture_output=True, text=True, timeout=20, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""
    return out.returncode, (out.stdout + out.stderr).strip()


def version_of(tool: str) -> str:
    code, out = run(tool, "--version") if shutil.which(tool) else (127, "")
    match = re.search(r"\d+\.\d+(\.\d+)?", out)
    return match.group(0) if code == 0 and match else ""


def pinned(pattern: str, path: str) -> str:
    match = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"))
    return match.group(1) if match else "?"


def check_tools() -> list[Result]:
    uv_pin = pinned(r'required-version = "==([\d.]+)"', "pyproject.toml")
    gitleaks_pin = pinned(r"gitleaks\n\s+rev: v([\d.]+)", ".pre-commit-config.yaml")
    uv, gitleaks = version_of("uv"), version_of("gitleaks")
    gh_code, _ = run("gh", "auth", "status")
    return [
        Result("uv", "0A", uv == uv_pin, uv or "not found", f"install uv {uv_pin} (§12, step 1)"),
        Result(
            "gitleaks",
            "0A",
            gitleaks == gitleaks_pin,
            gitleaks or "not found",
            f"install gitleaks {gitleaks_pin} (§12, step 1)",
        ),
        Result(
            "gh signed in",
            "0A",
            gh_code == 0,
            "yes" if gh_code == 0 else "no",
            "`gh auth login` with the repo and workflow scopes (§12, step 2)",
        ),
        Result(
            "claude",
            "0A",
            bool(shutil.which("claude")),
            version_of("claude") or "not found",
            "install Claude Code, with access to Opus 5.5 (§12, step 1)",
        ),
    ]


def check_git() -> list[Result]:
    _, email = run("git", "config", "user.email")
    _, hooks = run("git", "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    installed = all(
        (Path(hooks) / name).is_file() for name in ("pre-commit", "commit-msg", "pre-push")
    )
    return [
        Result(
            "git noreply email",
            "0A",
            email.endswith("@users.noreply.github.com"),
            email or "unset",
            "`git config user.email <id>+<login>@users.noreply.github.com` (§12, step 2)",
        ),
        Result(
            "git hooks",
            "0A",
            installed,
            "installed" if installed else "missing",
            "`uv run pre-commit install`",
        ),
    ]


def check_env(env_path: Path) -> list[Result]:
    env = read_env(env_path)
    ignored = run("git", "check-ignore", "-q", ".env")[0] == 0
    tracked = run("git", "ls-files", "--error-unmatch", ".env")[0] == 0
    results = [
        Result(
            ".env gitignored and untracked",
            "0A",
            ignored and not tracked,
            f"ignored={ignored}, tracked={tracked}",
            "restore `.gitignore`; never commit `.env`",
        ),
    ]
    if env_path.is_file():
        private = env_path.stat().st_mode & 0o077 == 0
        results.append(
            Result(
                ".env readable only by you",
                "0A",
                private or None,
                "mode 0600" if private else "readable by others",
                "`chmod 600 .env`",
            )
        )
    needs = {key: "0A" for key in APP_KEYS} | {"MISTRAL_API_KEY": "0B"}
    for key, phase in needs.items():
        step = "step 4" if key.startswith("FIELDTEST_APP") else "step 5"
        results.append(
            Result(
                key,
                phase,
                bool(env.get(key)),
                "set" if env.get(key) else "not set",
                f"add it to .env (§12, {step})",
            )
        )
    return results


def check_identity() -> list[Result]:
    identity = json.loads((ROOT / ".github" / "loop-identity.json").read_text(encoding="utf-8"))
    login = identity.get("bot_login") or ""
    return [
        Result(
            "loop identity",
            "0A",
            bool(login),
            login or "not configured",
            "`uv run python scripts/loop_auth.py identity` into .github/loop-identity.json (§12, step 4)",
        )
    ]


def check_later_phases() -> list[Result]:
    return [
        Result(
            "ollama",
            "3b",
            bool(shutil.which("ollama")),
            version_of("ollama") or "not found",
            "install Ollama and pull the model the Phase 3b plan names (§12, step 6)",
        ),
        Result(
            "docker",
            "5b",
            bool(shutil.which("docker")),
            version_of("docker") or "not found",
            "install Docker (§12, step 7)",
        ),
        Result(
            "node",
            "5b",
            bool(shutil.which("node")),
            version_of("node") or "not found",
            "install Node.js LTS (§12, step 7)",
        ),
    ]


def check_online() -> list[Result]:
    code, out = run(sys.executable, "-I", str(ROOT / "scripts" / "loop_auth.py"), "check")
    return [
        Result(
            "loop token",
            "0A",
            code == 0,
            out.splitlines()[-1] if out else "no output",
            "see the message; §12, step 4",
        )
    ]


def current_phase(progress: str) -> str:
    """The phase id on the `**Current phase:**` line.

    >>> current_phase("- **Current phase:** 3b — Local model")
    '3b'
    """
    match = re.search(r"\*\*Current phase:\*\*\s*(\w+)", progress)
    return match.group(1) if match else PHASES[0]


def main(argv: list[str]) -> int:
    if os.environ.get("FIELDTEST_DRIVER") == "1" and DRIVER_REPORT.is_file():
        # Inside the loop's sandbox `.env` can't be read, by design. The driver checked it
        # just before this session started.
        report = DRIVER_REPORT.read_text(encoding="utf-8")
        print("preflight: the driver's check before this session (the sandbox hides .env):")
        print(report, end="")
        return 0 if re.search(r"^preflight: 0 failing", report, re.MULTILINE) else 1
    upto = (
        PHASES[-1]
        if "--all" in argv
        else current_phase((ROOT / "docs" / "PROGRESS.md").read_text(encoding="utf-8"))
    )
    groups: list[Callable[[], list[Result]]] = [
        check_tools,
        check_git,
        lambda: check_env(ROOT / ".env"),
        check_identity,
        check_later_phases,
    ]
    if "--online" in argv:
        groups.append(check_online)
    limit = PHASES.index(upto)
    failed = 0
    for result in (r for group in groups for r in group()):
        if PHASES.index(result.phase) > limit:
            continue
        mark = "PASS" if result.ok else "WARN" if result.ok is None else "FAIL"
        failed += mark == "FAIL"
        suffix = "" if result.ok else f"  → {result.fix}"
        print(f"{mark}  {result.name} (from {result.phase}): {result.detail}{suffix}")
    print(f"preflight: {failed} failing, up to phase {upto}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
