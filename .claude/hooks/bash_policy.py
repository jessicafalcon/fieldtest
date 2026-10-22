#!/usr/bin/env python3
"""PreToolUse policy for every Bash call in fieldtest, by role. Stdlib only.

- Read-only agents (the reviewers, the plan critic and the arbiter): only inspection and
  check commands, with no chaining, redirection, expansion or file-writing flag.
- The merge gate: the same, plus the exact commands that run the PR guard, watch checks
  and squash-merge one pinned head commit.
- Every other session: no hook bypass, no force push, no push to `main` or to another
  remote, no merge, no PR approval, no mutating `gh api` or repo-settings call, no change
  to the GitHub identity the driver set, no secret reads, no shell write to `.gitignore`,
  `--env-file .env` only for the allowlisted live commands, and the git hooks installed
  before any commit or push.

The role is the payload's `agent_type`, or `--as NAME` from an agent's frontmatter
registration (a backup: Claude Code skips frontmatter hooks in an untrusted folder).
These rules stop accidents and injected instructions. The hard boundaries are elsewhere:
the GitHub App identity, which can't approve its own PRs or change settings (ADR 0003),
and the server-side ruleset (ADR 0001).
Any crash exits 2, so a broken policy blocks instead of allowing.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Keep in sync with the `name:` in each file under .claude/agents/.
READ_ONLY_AGENTS = {
    "code-reviewer",
    "security-reviewer",
    "coherence-auditor",
    "determinism-auditor",
    "test-reviewer",
    "plan-critic",
    "plan-arbiter",
}
MERGE_GATE = "merge-gate"

READ_ONLY = re.compile(
    r"^("
    r"uv run --frozen (--no-sync )?(pytest|mypy)( .*)?"
    r"|uv run --frozen (--no-sync )?ruff (check|format --check)( .*)?"
    r"|make (check|lint|typecheck|test|records)"
    r"|python3 scripts/guard\.py (--range \S+|--approved \d+)"
    r"|python3 scripts/preflight\.py( --all)?"
    r"|python3 scripts/check_records\.py"
    r"|python3 \.claude/hooks/determinism_guard\.py( .*)?"
    r"|git (diff|log|show|status|merge-base|rev-parse|ls-files|blame|grep|branch --show-current)( .*)?"
    r"|gh pr (view|diff|checks)( .*)?"
    r"|gh run (view|list)( .*)?"
    r"|gh issue (view|list)( .*)?"
    r")$"
)
MERGE_GATE_EXTRA = re.compile(
    r"^("
    r"python3 scripts/guard\.py --pr \d+"
    r"|gh pr checks \d+ --watch( --fail-fast)?( --interval \d+)?"
    r"|gh pr merge \d+ --squash --delete-branch --match-head-commit [0-9a-f]{40}"
    r")$"
)
# Chaining, redirection and substitution would let an allowed prefix run anything.
SHELL_META = re.compile(r"[;&|<>`\n]|\$\(")
SHELL_EXPANSION = re.compile(r"[$\\]|\{[^{}]*(,|\.\.)[^{}]*\}")
# Flags that write files or open a browser.
WRITING_FLAGS = frozenset(
    {
        "--fix",
        "--fix-only",
        "--add-noqa",
        "--config",
        "--cache-dir",
        "--write",
        "-w",
        "--web",
        "--output",
        "--output-file",
        "--basetemp",
        "--junitxml",
        "--junit-xml",
        "--override-ini",
        "--rootdir",
        "--update-golden",
        "--snapshot-update",
        "--install-types",
        "--html-report",
        "--txt-report",
        "--xml-report",
    }
)
WRITING_SHORT_FLAGS = ("-o", "-c")


def _writes(word: str) -> bool:
    if word.startswith("--"):
        return word.partition("=")[0] in WRITING_FLAGS
    return word in WRITING_FLAGS or word.startswith(WRITING_SHORT_FLAGS)


def allowed_for_agent(command: str, role: str) -> bool:
    """True when a read-only agent (or the merge gate) may run `command`.

    >>> allowed_for_agent("git diff main...HEAD -- src/", "code-reviewer")
    True
    >>> allowed_for_agent("git diff main...HEAD | head", "code-reviewer")
    False
    >>> allowed_for_agent("gh pr merge 3 --squash --delete-branch --match-head-commit " + "a" * 40, "code-reviewer")
    False
    """
    command = command.strip()
    pattern_ok = bool(READ_ONLY.match(command)) or (
        role == MERGE_GATE and bool(MERGE_GATE_EXTRA.match(command))
    )
    if not pattern_ok or SHELL_META.search(command) or SHELL_EXPANSION.search(command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return not any(_writes(word) for word in words)


# --- Every session -----------------------------------------------------------------------

# Keep in sync with HEREDOC in scripts/guard.py. A heredoc body is text (a PR body that
# mentions `git push --force` is not a push), so it is removed before parsing.
HEREDOC = re.compile(r"""(<<-?\s*(['"]?)(\w+)\2)([^\n]*)\n.*?^\t*\3$""", re.DOTALL | re.MULTILINE)
BYPASS_ENV = {"SKIP", "PRE_COMMIT_ALLOW_NO_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"}
# The driver sets the loop's GitHub identity (scripts/autopilot.sh); a command that
# overrides it would fall back to another credential on the machine.
IDENTITY_ENV = {
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_CONFIG_DIR",
    "GH_HOST",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GIT_ASKPASS",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
}
# The only commands that may load `.env`: the live calls the brief plans. Each one reads
# the one key it needs through its SDK. Keep in sync with PROJECT-BRIEF.md §12.
ENV_FILE_COMMANDS = re.compile(
    r"^uv run (--frozen )?--env-file \.env (python scripts/smoke_llm\.py|fieldtest (run|compare)\b)"
)
GITIGNORE_WRITERS = {
    "sed",
    "perl",
    "tee",
    "mv",
    "cp",
    "rm",
    "truncate",
    "dd",
    "ed",
    "ex",
    "awk",
    "python",
    "python3",
    "ln",
    "install",
    "chmod",
}
SECRET_VAR = re.compile(r"\$\{?[A-Z0-9_]*(API_KEY|TOKEN|SECRET|PASSWORD)\b")
SHELLS = {"bash", "sh", "zsh", "eval"}
COMMIT_VALUE_FLAGS = set("mFCctS")  # short flags of `git commit` that take a value


def segments(command: str) -> list[list[str]]:
    """Split a command line into simple commands (words), at operators and parentheses."""
    text = HEREDOC.sub(r"\1\4", command).replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    result: list[list[str]] = [[]]
    for token in lexer:
        if token and set(token) <= set(";&|()"):
            result.append([])
        else:
            result[-1].append(token)
    return [s for s in result if s]


def _strip_env(words: list[str]) -> tuple[list[str], set[str]]:
    names = set()
    while words and (words[0] == "env" or re.match(r"^[A-Za-z_]\w*=", words[0])):
        if words[0] != "env":
            names.add(words[0].split("=", 1)[0])
        words = words[1:]
    return words, names


def _git_parts(words: list[str]) -> tuple[list[str], str, list[str]]:
    """(global `-c` values, subcommand, its arguments) for a `git` command."""
    configs: list[str] = []
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] in {"-c", "-C", "--git-dir", "--work-tree", "--namespace"} and i + 1 < len(
            words
        ):
            if words[i] == "-c":
                configs.append(words[i + 1])
            i += 2
        else:
            if words[i].startswith("--config-env"):
                configs.append(words[i])
            i += 1
    sub = words[i] if i < len(words) else ""
    return configs, sub, words[i + 1 :]


def _targets_main(args: list[str]) -> bool:
    refspecs = [a for a in args if not a.startswith("-")][1:]  # after the remote
    return any(re.fullmatch(r"\+?(?:[^:]*:)?(?:refs/heads/)?main", spec) for spec in refspecs)


def violations(words: list[str], role: str, cwd: Path) -> list[str]:
    """Why one simple command is not allowed for a general session, or []."""
    found = secret_reads(words) + gitignore_writes(words)
    stripped, env_names = _strip_env(words)
    if bypass := env_names & BYPASS_ENV:
        return [*found, f"{', '.join(sorted(bypass))}= skips or rewires the git hooks"]
    if identity := env_names & IDENTITY_ENV:
        found.append(f"{', '.join(sorted(identity))}= changes the GitHub identity the driver set")
    if stripped[:1] == ["unset"] and set(stripped[1:]) & IDENTITY_ENV:
        found.append("unsetting the loop's identity would fall back to another credential")
    if words[:1] == ["env"] and any(w in {"-u", "--unset"} or w.startswith("-u") for w in words):
        found.append("unsetting the loop's identity would fall back to another credential")
    if any(Path(w).name == "loop_auth.py" for w in stripped):
        found.append("scripts/loop_auth.py is the driver's; sessions never mint tokens")
    if not stripped:
        if words[:1] == ["env"]:
            found.append("printing the environment can expose secrets")
        return found
    head = Path(stripped[0]).name
    if head in SHELLS:
        nested = (
            stripped[2] if len(stripped) > 2 and stripped[1] == "-c" else " ".join(stripped[1:])
        )
        return [*found, *(v for seg in segments(nested) for v in violations(seg, role, cwd))]
    if head == "printenv":
        found.append("printing the environment can expose secrets")
    elif head == "git":
        found += _git_violations(stripped, cwd)
    elif head == "gh":
        found += _gh_violations(stripped, role)
    return found


def _git_violations(words: list[str], cwd: Path) -> list[str]:
    configs, sub, args = _git_parts(words)
    if any("hookspath" in c.lower() for c in configs):
        return ["core.hooksPath rewires the git hooks"]
    if sub == "config" and any("hookspath" in a.lower() for a in args):
        return ["core.hooksPath rewires the git hooks"]
    if any(c.lower().startswith("credential") for c in configs) or (
        sub == "config" and any(a.lower().startswith("credential") for a in args)
    ):
        return ["git credentials are set by the driver (the loop's App identity)"]
    if sub == "remote" and args[:1] and args[0] in {"add", "set-url", "rename", "remove", "rm"}:
        return ["remotes are fixed: fieldtest pushes only to origin"]
    found = []
    if sub == "commit":
        if "--no-verify" in args or any(_short_bundle_has(a, "n") for a in args):
            found.append("--no-verify skips the commit guard")
        found += _hooks_missing(cwd)
    if sub == "push":
        if "--no-verify" in args:
            found.append("--no-verify skips the push guard")
        force = {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror"}
        if (
            force & {a.partition("=")[0] for a in args}
            or any(a.startswith("+") for a in args)
            or any(_short_bundle_has(a, "f") for a in args)
        ):
            found.append("force push is never needed: merge main into the branch instead")
        positional = [a for a in args if not a.startswith("-")]
        if positional and positional[0] != "origin":
            found.append("push only to origin")
        to_main = _targets_main(args) or (len(positional) <= 1 and _current_branch(cwd) == "main")
        if to_main and _remote_has_main(cwd):
            found.append("main changes only through a squash-merged PR")
        found += _hooks_missing(cwd)
    return found


def _short_bundle_has(word: str, flag: str) -> bool:
    """`-nm` or `-an` carry `-n`; in `-mn`, `n` is the message, not a flag."""
    if not re.fullmatch(r"-[A-Za-z]+", word):
        return False
    for char in word[1:]:
        if char == flag:
            return True
        if char in COMMIT_VALUE_FLAGS:
            return False
    return False


def _gh_violations(words: list[str], role: str) -> list[str]:
    args = words[1:]
    group, action = [*args, "", ""][:2]
    if (group, action) == ("pr", "merge") and role != MERGE_GATE:
        return ["only the merge-gate agent merges, after its checks (CLAUDE.md, the PR loop)"]
    if (group, action) == ("pr", "review") and any(
        a in {"--approve", "-a"} or _short_bundle_has(a, "a") for a in args[2:]
    ):
        return ["approving a PR is the human's decision (a guardrail change needs it)"]
    if group == "repo" and action in {"create", "delete", "edit", "rename", "archive", "unarchive"}:
        return ["repository settings are human-owned (scripts/setup_github.sh)"]
    if group in {"secret", "variable", "ruleset"} and action not in {"list", "view", ""}:
        return ["secrets, variables and rulesets are human-owned"]
    if group == "auth" and (action == "token" or "--show-token" in args or "-t" in args):
        return ["printing the GitHub token exposes it"]
    if group == "auth" and action in {"login", "logout", "switch", "refresh", "setup-git"}:
        return ["the GitHub identity is set by the driver (scripts/autopilot.sh)"]
    if (group, action) in {
        ("release", "delete"),
        ("issue", "delete"),
        ("issue", "transfer"),
        ("workflow", "disable"),
        ("label", "delete"),
    }:
        return [f"`gh {group} {action}` is human-owned"]
    if group == "api":
        method = _api_method(args)
        # Fields make gh send a POST unless the method says otherwise.
        fields = {"-f", "-F", "--field", "--raw-field", "--input"}
        implicit_post = any(a.partition("=")[0] in fields for a in args)
        if method not in {"", "GET"} or (implicit_post and method != "GET"):
            return [
                "mutating `gh api` calls are human-owned; use the gh subcommand the loop allows"
            ]
    return []


def _api_method(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg in {"-X", "--method"} and i + 1 < len(args):
            return args[i + 1].upper()
        if arg.startswith("--method="):
            return arg.partition("=")[2].upper()
        if arg.startswith("-X") and len(arg) > 2:
            return arg[2:].upper()
    return ""


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False
    )
    return result.stdout.strip()


def _current_branch(cwd: Path) -> str:
    return _git(cwd, "branch", "--show-current")


def _remote_has_main(cwd: Path) -> bool:
    """False only before the first push: bootstrapping `main` is the one direct push."""
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "main"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return result.returncode != 2  # 2: reachable, no such ref; any error counts as present


def _hooks_missing(cwd: Path) -> list[str]:
    hooks = Path(
        _git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "hooks") or ".git/hooks"
    )
    missing = [
        name
        for name in ("pre-commit", "commit-msg", "pre-push")
        if not (hooks / name).is_file()
        or "pre-commit" not in (hooks / name).read_text(errors="replace")
    ]
    if missing:
        return [f"git hooks not installed ({', '.join(missing)}): run `uv run pre-commit install`"]
    return []


def secret_reads(words: list[str]) -> list[str]:
    """A word naming `.env`, `.private/` or a secret variable, outside `--env-file .env`.

    Words, not the raw text: a commit message that mentions `.env` is one quoted word.
    """
    found = []
    for i, word in enumerate(words):
        name = word.rstrip("/").rsplit("/", 1)[-1]
        if re.fullmatch(r"\.env(\.[\w-]+)?", name) and name != ".env.example":
            loads = i > 0 and words[i - 1] == "--env-file"
            if not loads:
                found.append(".env is never printed, copied, moved or edited from the shell")
            elif not ENV_FILE_COMMANDS.match(" ".join(words)):
                found.append(
                    "`--env-file .env` only for the smoke call and `fieldtest run|compare` "
                    "(PROJECT-BRIEF.md §12)"
                )
        if word.startswith("--env-file=") and word.partition("=")[2].endswith(".env"):
            found.append("use `--env-file .env` as two words, with an allowlisted command")
        if ".autopilot/gh" in word:
            found.append(".autopilot/gh/ holds the loop's token; never read it")
        if word == ".private" or word.startswith(".private/") or "/.private" in word:
            found.append(".private/ is the human's; Claude never reads it by hand")
        if SECRET_VAR.search(word):
            found.append("expanding a secret variable can print it")
    return found


def gitignore_writes(words: list[str]) -> list[str]:
    """A shell command that could rewrite `.gitignore` (edits go through Edit/Write, where
    protect_files.py keeps its required lines)."""
    names = [Path(w).name for w in words]
    if ".gitignore" not in names:
        return []
    head = Path(words[0]).name if words else ""
    redirected = any(w in {">", ">>"} for w in words)
    git_rewrite = head == "git" and any(w in {"checkout", "restore", "rm", "mv"} for w in words)
    if head in GITIGNORE_WRITERS or redirected or git_rewrite:
        return ["`.gitignore` changes only through Edit/Write, which keep its secret lines"]
    return []


def check(command: str, role: str, cwd: Path) -> list[str]:
    """Every reason `command` is blocked for `role`, or [] when it may run."""
    if role in READ_ONLY_AGENTS or role == MERGE_GATE:
        if allowed_for_agent(command, role):
            return []
        what = "the merge gate" if role == MERGE_GATE else "review agents"
        return [
            f"{what} run only the allowlisted check and read commands; report instead of acting"
        ]
    try:
        parts = segments(command)
    except ValueError:
        return ["unbalanced quotes: the command can't be checked"]
    found: list[str] = []
    for words in parts:
        found += violations(words, role, cwd)
    return found


def main() -> int:
    payload = json.load(sys.stdin)
    argv = sys.argv[1:]
    role = argv[argv.index("--as") + 1] if "--as" in argv else payload.get("agent_type") or ""
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    reasons = check(command, role, cwd)
    if not reasons:
        return 0
    print("bash-policy: blocked.", file=sys.stderr)
    for reason in dict.fromkeys(reasons):
        print(f"  - {reason}", file=sys.stderr)
    print("If the work truly needs this, escalate (CLAUDE.md, Escalation).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # exit 1 would not block; a broken policy must
        print(f"bash-policy: blocked, the hook failed: {error!r}", file=sys.stderr)
        sys.exit(2)
