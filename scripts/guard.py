#!/usr/bin/env python3
"""The one guard for everything that reaches the public repo. Stdlib only.

Modes (each exits non-zero on a finding and prints the reasons on stderr):

  --staged            git pre-commit: staged paths and added lines
  --commit-msg FILE   git commit-msg: subject form, secrets, personal data, private terms
  --push              git pre-push: every commit not yet on `origin`, plus gitleaks
  --range BASE..HEAD  CI and reviewers: the same per-commit checks over a range; in CI it
                      also applies the PR rules (guardrail label, progress record)
  --pr N              the merge gate: the PR's metadata, commits, diff, checks and reviews
  --hook              Claude Code PreToolUse: text written into the repo, and the text of
                      commands that publish (commits, tags, PRs, issues, releases)

Private terms come from `.private/denylist.txt` (gitignored). Without it, that one rule is
skipped; CI has no denylist, so the local hooks are where it applies.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard_rules import (
    DEPENDABOT,
    Finding,
    added_lines_by_file,
    check_author_email,
    check_commit_subject,
    forbidden_path,
    is_guardrail_path,
    load_terms,
    required_reviews,
    scan_text,
)

HUMAN_LABEL = "human-approved"
PROGRESS = "docs/PROGRESS.md"
REQUIRED_CHECKS = ("check", "security")
GUARD_FILES = ("scripts/guard.py", "scripts/guard_rules.py")
REVIEW_MARKER = re.compile(
    r"<!-- fieldtest-review agent=(?P<agent>[a-z-]+) verdict=(?P<verdict>ready|ready-after-fixes|not-ready)"
    r" sha=(?P<sha>[0-9a-f]{7,40}) -->"
)
FIXLOG_MARKER = re.compile(r"<!-- fieldtest-fixlog sha=(?P<sha>[0-9a-f]{7,40}) -->")


def repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    return Path(out.stdout.strip() or ".").resolve()


def terms_for(root: Path) -> list[re.Pattern[str]]:
    denylist = root / ".private" / "denylist.txt"
    return load_terms(denylist.read_text(encoding="utf-8")) if denylist.is_file() else []


def git(*args: str, root: Path) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout


def report(findings: list[Finding], title: str) -> int:
    if not findings:
        return 0
    print(f"guard: {title} blocked.", file=sys.stderr)
    for finding in sorted(set(findings)):
        print(f"  - {finding}", file=sys.stderr)
    print(
        "Fix the content (never weaken the rule). Secrets go in .env, private context in "
        ".private/; see SECURITY.md.",
        file=sys.stderr,
    )
    return 1


# --- Shared checks -----------------------------------------------------------------------


def check_paths(paths: list[str], where: str) -> list[Finding]:
    return [
        Finding(f"{where} {p}", "private-path", why) for p in paths if (why := forbidden_path(p))
    ]


def check_diff(diff: str, where: str, terms: list[re.Pattern[str]]) -> list[Finding]:
    findings: list[Finding] = []
    for path, added in added_lines_by_file(diff).items():
        findings += scan_text(added, f"{where} {path}", terms, path=path)
    return findings


def check_message(message: str, where: str, terms: list[re.Pattern[str]]) -> list[Finding]:
    lines = [ln for ln in message.splitlines() if not ln.startswith("#")]
    subject = lines[0] if lines else ""
    findings = []
    if why := check_commit_subject(subject):
        findings.append(Finding(where, "commit-message", why))
    # Co-author trailers carry noreply addresses only; anything else is personal data.
    findings += scan_text("\n".join(lines), where, terms)
    return findings


def check_commits(shas: list[str], root: Path, terms: list[re.Pattern[str]]) -> list[Finding]:
    findings: list[Finding] = []
    for sha in shas:
        where = f"commit {sha[:9]}"
        meta = git("show", "-s", "--format=%ae%n%ce%n%B", sha, root=root)
        author, committer, message = meta.split("\n", 2)
        for email in {author, committer}:
            if why := check_author_email(email):
                findings.append(Finding(where, "author-email", why))
        findings += check_message(message, where, terms)
        paths = git(
            "diff-tree",
            "--no-commit-id",
            "-r",
            "--name-only",
            "--diff-filter=ACMR",
            "--root",
            sha,
            root=root,
        ).splitlines()
        findings += check_paths(paths, where)
        diff = git("show", "--format=", "--no-color", "-U0", "--diff-filter=ACMR", sha, root=root)
        findings += check_diff(diff, where, terms)
    return findings


def pr_rules(paths: list[str], *, author: str, labels: list[str]) -> list[Finding]:
    """Rules that apply to a PR as a whole, shared by CI and the merge gate."""
    findings = []
    guardrails = sorted(p for p in paths if is_guardrail_path(p))
    if guardrails and HUMAN_LABEL not in labels:
        findings.append(
            Finding(
                "PR",
                "guardrail-change",
                f"changes {', '.join(guardrails)}; merges only after a human adds the "
                f"`{HUMAN_LABEL}` label (escalate)",
            )
        )
    if author != DEPENDABOT and PROGRESS not in paths:
        findings.append(
            Finding(
                "PR", "records", f"{PROGRESS} is not updated; every PR moves the status forward"
            )
        )
    return findings


# --- Modes -------------------------------------------------------------------------------


def mode_staged(root: Path) -> int:
    terms = terms_for(root)
    paths = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", root=root).splitlines()
    diff = git("diff", "--cached", "--no-color", "-U0", "--diff-filter=ACMR", root=root)
    return report(check_paths(paths, "staged") + check_diff(diff, "staged", terms), "commit")


def mode_commit_msg(root: Path, message_file: str) -> int:
    message = Path(message_file).read_text(encoding="utf-8", errors="replace")
    # Drop everything from git's verbose-diff scissors line down.
    message = message.split("# ------------------------ >8 ------------------------")[0]
    return report(check_message(message, "commit message", terms_for(root)), "commit message")


def mode_push(root: Path) -> int:
    to_ref = os.environ.get("PRE_COMMIT_TO_REF") or "HEAD"
    if set(to_ref) == {"0"}:
        return 0  # deleting a remote branch publishes nothing
    shas = git("rev-list", to_ref, "--not", "--remotes=origin", root=root).split()
    if not shas:
        return 0
    findings = check_commits(shas, root, terms_for(root))
    findings += gitleaks(root, f"{to_ref} --not --remotes=origin")
    return report(findings, "push")


def gitleaks(root: Path, log_opts: str) -> list[Finding]:
    if shutil.which("gitleaks") is None:
        return [Finding("push", "gitleaks", "gitleaks is not on PATH; install it (see README)")]
    result = subprocess.run(
        ["gitleaks", "git", "--redact", "--no-banner", f"--log-opts={log_opts}", "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    print(result.stdout + result.stderr, file=sys.stderr)
    return [Finding("push", "gitleaks", "gitleaks found a secret in the commits being pushed")]


def mode_range(root: Path, spec: str) -> int:
    base, _, head = spec.partition("..")
    shas = git("rev-list", "--reverse", spec, root=root).split()
    findings = check_commits(shas, root, terms_for(root))
    author = os.environ.get("FIELDTEST_PR_AUTHOR")
    if author is not None:  # CI on a pull request: apply the PR rules too
        labels = json.loads(os.environ.get("FIELDTEST_PR_LABELS") or "[]")
        paths = git("diff", "--name-only", f"{base}...{head or 'HEAD'}", root=root).splitlines()
        findings += pr_rules(paths, author=author, labels=labels)
    return report(findings, f"range {spec}")


# --- PR mode (the merge gate) --------------------------------------------------------------


def gh_json(*args: str, root: Path) -> dict[str, Any]:
    out = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    if not isinstance(data, dict):
        raise TypeError(f"gh {args[0]} {args[1]} returned {type(data).__name__}, not an object")
    return data


def evaluate_pr(
    pr: dict, diff: str, *, owner: str, terms: list[re.Pattern[str]]
) -> tuple[list[Finding], list[str]]:
    """Every merge-blocking finding for a PR, and the owner's review notes for the gate.

    `pr` is `gh pr view --json` output with the fields listed in `PR_FIELDS`.
    """
    findings: list[Finding] = []
    author = pr["author"]["login"]
    if pr["state"] != "OPEN" or pr["isDraft"]:
        findings.append(Finding("PR", "state", f"state {pr['state']}, draft={pr['isDraft']}"))
    if pr["baseRefName"] != "main":
        findings.append(Finding("PR", "base", f"base is {pr['baseRefName']}, not main"))
    if pr["isCrossRepository"]:
        findings.append(
            Finding("PR", "fork", "head is in a fork; external PRs are never auto-merged")
        )
    if author not in {owner, DEPENDABOT}:
        findings.append(Finding("PR", "author", f"author {author} is not the owner or Dependabot"))

    if why := check_commit_subject(pr["title"]):
        findings.append(Finding("PR title", "commit-message", why))
    findings += scan_text(pr["title"], "PR title", terms)
    findings += scan_text(pr["body"], "PR body", terms)

    paths = [f["path"] for f in pr["files"]]
    findings += check_paths(paths, "PR")
    findings += check_diff(diff, "PR diff", terms)
    for commit in pr["commits"]:
        for person in commit["authors"]:
            if why := check_author_email(person.get("email", "")):
                findings.append(Finding(f"commit {commit['oid'][:9]}", "author-email", why))
        message = f"{commit['messageHeadline']}\n{commit['messageBody']}"
        findings += check_message(message, f"commit {commit['oid'][:9]}", terms)

    labels = [label["name"] for label in pr["labels"]]
    findings += pr_rules(paths, author=author, labels=labels)

    rollup = {c.get("name") or c.get("context"): c for c in pr["statusCheckRollup"]}
    for name in REQUIRED_CHECKS:
        check = rollup.get(name)
        result = (check or {}).get("conclusion") or (check or {}).get("state") or "MISSING"
        if result.upper() != "SUCCESS":
            findings.append(Finding("PR", "checks", f"required check `{name}` is {result}"))
    for name, check in sorted(rollup.items()):
        result = (check.get("conclusion") or check.get("state") or "PENDING").upper()
        if result not in {"SUCCESS", "SKIPPED", "NEUTRAL"} and name not in REQUIRED_CHECKS:
            findings.append(Finding("PR", "checks", f"check `{name}` is {result}"))
    if pr["mergeable"] != "MERGEABLE":
        findings.append(Finding("PR", "mergeable", f"mergeable={pr['mergeable']} (conflicts?)"))

    review_findings, notes = evaluate_reviews(pr, paths, owner=owner)
    return findings + review_findings, notes


def evaluate_reviews(pr: dict, paths: list[str], *, owner: str) -> tuple[list[Finding], list[str]]:
    """Check that each required agent reported, and that fixes after a report are logged.

    Only the owner's comments count: on a public repo anyone can comment, and a comment
    from anyone else is untrusted text, never a review.
    """
    phase_exit = bool(re.search(r"(?im)^Phase exit: \S+", pr["body"]))
    required = required_reviews(paths, author=pr["author"]["login"], phase_exit=phase_exit)
    commits = [c["oid"] for c in pr["commits"]]
    head = commits[-1] if commits else ""
    latest: dict[str, tuple[int, str, str]] = {}
    fixlogs: list[tuple[int, str]] = []
    notes: list[str] = []
    for index, comment in enumerate(pr["comments"]):
        if comment["author"]["login"] != owner:
            continue
        body = comment["body"]
        for match in REVIEW_MARKER.finditer(body):
            latest[match["agent"]] = (index, match["verdict"], match["sha"])
            notes.append(f"--- review by {match['agent']} ({match['verdict']}) ---\n{body}")
        for match in FIXLOG_MARKER.finditer(body):
            fixlogs.append((index, match["sha"]))
            notes.append(f"--- fix log at {match['sha'][:9]} ---\n{body}")

    findings = []
    for agent in sorted(required):
        if agent not in latest:
            findings.append(Finding("PR", "review", f"no report from `{agent}`"))
            continue
        index, verdict, sha = latest[agent]
        if verdict == "not-ready":
            findings.append(Finding("PR", "review", f"`{agent}` says not-ready; fix and re-run it"))
        if not any(c.startswith(sha) for c in commits):
            findings.append(
                Finding("PR", "review", f"`{agent}` reviewed {sha[:9]}, not a PR commit")
            )
        reviewed_head = head.startswith(sha)
        if (verdict == "ready-after-fixes" or not reviewed_head) and not any(
            i > index and head.startswith(s) for i, s in fixlogs
        ):
            findings.append(
                Finding(
                    "PR",
                    "review",
                    f"`{agent}` reviewed {sha[:9]}; commits after it need a fix log at the head",
                )
            )
    return findings, notes


PR_FIELDS = (
    "number,state,isDraft,baseRefName,isCrossRepository,author,title,body,files,commits,"
    "labels,statusCheckRollup,mergeable,comments,headRefOid"
)


def mode_pr(root: Path, number: str) -> int:
    if not number.isdigit():
        print("guard: --pr takes a PR number", file=sys.stderr)
        return 2
    base_result = run_base_guard_if_modified(root, ["--pr", number])
    if base_result is not None:
        return base_result
    pr = gh_json("pr", "view", number, "--json", PR_FIELDS, root=root)
    repo = gh_json("repo", "view", "--json", "owner", root=root)
    diff = subprocess.run(
        ["gh", "pr", "diff", number, "--color=never"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    findings, notes = evaluate_pr(pr, diff, owner=repo["owner"]["login"], terms=terms_for(root))
    print(f"PR #{number} head {pr['headRefOid']}")
    print("\n".join(notes) if notes else "(no owner review comments)")
    if findings:
        return report(findings, f"merge of PR #{number}")
    print(f"guard: PR #{number} passes every deterministic merge rule.")
    return 0


def run_base_guard_if_modified(root: Path, args: list[str]) -> int | None:
    """Judge a PR with main's guard when the working tree's guard differs from it.

    A PR that weakens the guard must not be judged by its own weaker copy. Returns the
    base guard's exit code, or None when this guard is main's and should run itself.
    """
    if os.environ.get("FIELDTEST_GUARD_IS_BASE"):
        return None
    try:
        git("fetch", "--quiet", "origin", "main", root=root)
    except subprocess.CalledProcessError:
        return None  # no origin/main yet
    on_main = all(
        subprocess.run(
            ["git", "cat-file", "-e", f"origin/main:{name}"],
            cwd=root,
            capture_output=True,
            check=False,
        ).returncode
        == 0
        for name in GUARD_FILES
    )
    if not on_main:
        return None  # main has no guard yet: the first PR is judged by its own
    same = (
        subprocess.run(
            ["git", "diff", "--quiet", "origin/main", "--", *GUARD_FILES], cwd=root, check=False
        ).returncode
        == 0
    )
    if same:
        return None
    print("guard: this checkout's guard differs from main's; running main's.", file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        for name in GUARD_FILES:
            text = git("show", f"origin/main:{name}", root=root)
            (Path(tmp) / Path(name).name).write_text(text, encoding="utf-8")
        env = {**os.environ, "FIELDTEST_GUARD_IS_BASE": "1"}
        result = subprocess.run(
            [sys.executable, str(Path(tmp) / "guard.py"), *args], cwd=root, env=env, check=False
        )
    return result.returncode


# --- Hook mode (Claude Code PreToolUse) ------------------------------------------------------

# A shell word: unquoted characters and quoted strings, so a message passed in quotes is
# one word and a flag named inside it is never read as a real flag.
SHELL_WORD = re.compile(r"""(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s"'])+""")
_W = SHELL_WORD.pattern
PUBLISHING_COMMAND = re.compile(
    rf"\b(git(\s+(-[Cc]\s+{_W}|-[pP]|--[\w-]+((=|\s+){_W})?))*\s+(commit|tag|notes)"
    r"|gh\s+(pr|issue)\s+(create|edit|comment|review|merge|close)"
    r"|gh\s+release\s+(create|edit))\b"
)
# A heredoc body is text, not words: its quotes need not balance.
HEREDOC = re.compile(
    r"""(<<-?\s*(['"]?)(\w+)\2)([^\n]*)\n(?P<body>.*?)^\t*\3$""", re.DOTALL | re.MULTILINE
)
FILE_FLAGS = ("-F", "--file", "--body-file", "--notes-file")
TEXT_FLAGS = ("-m", "--message", "-t", "--title", "-b", "--body", "-n", "--notes")


def _unquote(word: str) -> str:
    try:
        text = "".join(shlex.split(word))
    except ValueError:
        return word
    return text if word.startswith("'") else os.path.expandvars(text)


def flag_values(command: str, flags: tuple[str, ...]) -> list[str]:
    """Values given to `flags`: `--flag V`, `--flag=V`, `-FV`, or last in a bundle `-dF V`.

    >>> flag_values('gh pr create -t "use -F x" --body-file=b.md -Fc.md -dF d.md', ("-F", "--body-file"))
    ['b.md', 'c.md', 'd.md']
    """
    words = SHELL_WORD.findall(HEREDOC.sub(r"\1\4", command))
    short = "".join(f[1] for f in flags if len(f) == 2)
    bundle = re.compile(rf"-[A-Za-z]*?[{short}](.*)") if short else None
    values: list[str] = []
    for i, word in enumerate(words):
        name, equals, value = word.partition("=")
        if name in flags and (equals or i + 1 < len(words)):
            values.append(_unquote(value if equals else words[i + 1]))
        elif bundle and not word.startswith("--") and (match := bundle.fullmatch(word)):
            if match.group(1):
                values.append(_unquote(match.group(1)))
            elif i + 1 < len(words):
                values.append(_unquote(words[i + 1]))
    return values


def read_named_file(name: str, bases: list[Path]) -> str:
    """Read a file named by `-F`/`--body-file`; fail closed if it can't be found."""
    for base in bases:
        path = base / Path(name).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError(2, "cannot read the file to check it", name)


def hook_texts(tool: str, tool_input: dict, root: Path, cwd: Path) -> list[tuple[str, str, bool]]:
    """(where, text, check personal data) for every text this tool call would publish."""
    if tool == "Bash":
        command = tool_input.get("command", "")
        if not PUBLISHING_COMMAND.search(command):
            return []
        # The shell would publish text the guard never sees: a substitution outside a
        # heredoc, or inside one whose delimiter is unquoted (`<<EOF` expands, `<<'EOF'`
        # does not).
        unquoted_heredocs = [m["body"] for m in HEREDOC.finditer(command) if not m.group(2)]
        if any(
            re.search(r"\$\(|`", text) for text in [HEREDOC.sub("", command), *unquoted_heredocs]
        ):
            raise FileNotFoundError(2, "command substitution hides the text", "$(...)")
        bases = [cwd, *(cwd / d for d in flag_values(command, ("-C",)))]
        files = flag_values(command, FILE_FLAGS)
        if "-" in files and not HEREDOC.search(command):
            raise FileNotFoundError(2, "stdin is visible only as a heredoc", "-")
        # The whole command for secrets and terms; personal data only in the published
        # text, since the command itself names local paths (`-F /abs/path`, `cd`).
        texts = [("command", command, False)]
        texts += [("heredoc", m["body"], True) for m in HEREDOC.finditer(command)]
        texts += [("message", v, True) for v in flag_values(command, TEXT_FLAGS)]
        texts += [(name, read_named_file(name, bases), True) for name in files if name != "-"]
        return texts
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return []
    try:
        rel = Path(file_path).resolve().relative_to(root).as_posix()
    except ValueError:
        return []  # outside the project: memory, scratchpad
    edits = tool_input.get("edits") or []
    pieces = [
        tool_input.get("content", ""),
        tool_input.get("new_string", ""),
        tool_input.get("new_source", ""),
        *(edit.get("new_string", "") for edit in edits),
    ]
    return [(rel, "\n".join(p for p in pieces if p), True)]


def mode_hook(root: Path) -> int:
    payload = json.load(sys.stdin)
    cwd = Path(payload.get("cwd") or root)
    tool = payload.get("tool_name", "")
    try:
        texts = hook_texts(tool, payload.get("tool_input") or {}, root, cwd)
    except OSError as error:
        print(
            f"guard: blocked, cannot read {error.filename!r} to check it. Pass an existing "
            "absolute path, or put the text inline (a heredoc for stdin).",
            file=sys.stderr,
        )
        return 2
    terms = terms_for(root)
    findings: list[Finding] = []
    for where, text, personal in texts:
        path = where if tool != "Bash" else None
        findings += scan_text(text, where, terms, path=path, personal=personal)
    return 2 if report(findings, f"{tool} call") else 0


def main(argv: list[str]) -> int:
    root = repo_root()
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    mode, *rest = argv
    if mode == "--staged":
        return mode_staged(root)
    if mode == "--commit-msg" and rest:
        return mode_commit_msg(root, rest[0])
    if mode == "--push":
        return mode_push(root)
    if mode == "--range" and rest and ".." in rest[0]:
        return mode_range(root, rest[0])
    if mode == "--pr" and rest:
        return mode_pr(root, rest[0])
    if mode == "--hook":
        return mode_hook(root)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    hook_mode = sys.argv[1:2] == ["--hook"]
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as error:
        # A broken guard must block, never let content through. In hook mode only exit 2
        # blocks the tool call.
        print(f"guard: blocked, the guard failed: {error!r}", file=sys.stderr)
        sys.exit(2 if hook_mode else 1)
