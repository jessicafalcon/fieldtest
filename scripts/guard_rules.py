"""Pure rules for what may reach the public repo: paths, secrets, personal data, private terms.

No I/O here: `guard.py` gathers text from git, GitHub or a hook payload and calls these
functions, so every rule is unit-tested on plain strings. Stdlib only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath

__all__ = [
    "GUARDRAIL_PATHS",
    "REQUIRED_IGNORES",
    "REVIEW_AGENTS",
    "Finding",
    "added_lines_by_file",
    "approved_on_head",
    "check_author_email",
    "check_commit_subject",
    "diffs_by_file",
    "forbidden_path",
    "frozen_paths",
    "gitignore_findings",
    "guarded_regions",
    "is_docs_only",
    "is_guardrail_path",
    "load_terms",
    "matches_frozen",
    "missing_ignores",
    "removed_lines_by_file",
    "required_reviews",
    "scan_text",
    "touches_guarded_region",
]


@dataclass(frozen=True, order=True)
class Finding:
    """One violation. `detail` never repeats a secret's value."""

    where: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: [{self.rule}] {self.detail}"


# --- Paths that never enter a commit -------------------------------------------------

_KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks"}
_KEY_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pypirc"}


def forbidden_path(path: str) -> str | None:
    """Why `path` must never be committed, or None.

    >>> forbidden_path(".env.example") is None
    True
    >>> forbidden_path(".private/notes.md")
    '.private/ is local-only'
    """
    p = PurePosixPath(path)
    name = p.name
    if p.parts[:1] == (".private",):
        return ".private/ is local-only"
    if name == "CLAUDE.local.md":
        return "CLAUDE.local.md is personal context"
    if p.parts[:2] == (".claude", "settings.local.json"):
        return "local Claude Code settings"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "environment file (secrets live only in the local .env)"
    if p.suffix.lower() in _KEY_SUFFIXES or name in _KEY_NAMES:
        return "private key, certificate or credentials file"
    return None


# --- Guardrails: files whose change needs a human ----------------------------------------

# Keep in sync with "Guardrails" in CLAUDE.md and ADRs 0001 and 0004. A PR that touches
# any of these merges only with the repo owner's approving review on its head commit. The
# loop acts as its own GitHub App, and a PR's author can never approve it (ADR 0003).
# The list covers what constrains the loop and what defines its authority: the agents
# (reviewers, arbiter, merge gate), the skills that decide when to escalate or accept, the
# sandbox, and the pre-registration file.
GUARDRAIL_PATHS = (
    ".gitignore",
    ".claude/settings.json",
    ".claude/sandbox.autopilot.json",
    ".claude/hooks/",
    ".claude/agents/",
    ".claude/skills/autopilot/",
    ".claude/skills/phase-start/",
    ".claude/skills/phase-review/",
    ".claude/skills/determinism-contract/",
    ".claude/skills/fieldtest-security/",
    "config/preregistration.json",
    ".github/workflows/",
    ".github/dependabot.yml",
    ".github/loop-identity.json",
    ".pre-commit-config.yaml",
    "scripts/guard.py",
    "scripts/guard_rules.py",
    "scripts/autopilot.sh",
    "scripts/loop_auth.py",
    "scripts/setup_github.sh",
)

# --- Guarded regions and pre-registration (ADR 0004) --------------------------------------

# Text between these markers, in any file on main, changes only with the owner's approval:
# the brief's principles, determinism contract, outcome taxonomy, recommendation rule,
# acceptance criteria and escalation policy, and the matching parts of CLAUDE.md.
GUARD_START = "<!-- guarded:start -->"
GUARD_END = "<!-- guarded:end -->"


def guarded_regions(text: str) -> list[tuple[int, int]] | None:
    """1-based (start, end) line ranges between the markers; None if they don't pair up.

    >>> guarded_regions("a\\n<!-- guarded:start -->\\nb\\n<!-- guarded:end -->\\n")
    [(2, 4)]
    >>> guarded_regions("<!-- guarded:start -->\\nb\\n") is None
    True
    """
    regions: list[tuple[int, int]] = []
    start: int | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if GUARD_START in line:
            if start is not None:
                return None
            start = number
        elif GUARD_END in line:
            if start is None:
                return None
            regions.append((start, number))
            start = None
    return None if start is not None else regions


def diffs_by_file(diff: str) -> dict[str, str]:
    """A unified diff split per file, keyed by the old path (the new one for an added file)."""
    files: dict[str, list[str]] = {}
    current: list[str] = []
    old = new = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current = []
            old = new = ""
            continue
        if line.startswith("--- ") and not old:
            old = line[6:] if line.startswith("--- a/") else ""
            continue
        elif line.startswith("+++ ") and not new:
            new = line[6:] if line.startswith("+++ b/") else ""
            files[old or new] = current
            continue
        current.append(line)
    return {name: "\n".join(lines) for name, lines in files.items()}


def _old_lines_touched(file_diff: str) -> tuple[set[int], set[int]]:
    """(old lines removed, old lines after which text is inserted) in one file's hunks."""
    removed: set[int] = set()
    inserted_after: set[int] = set()
    old_line = 0
    for line in file_diff.splitlines():
        if line.startswith("@@"):
            header = line.split()[1]  # -a,b
            start, _, count = header[1:].partition(",")
            # With a zero count, `a` is the line the hunk inserts after.
            old_line = int(start) + (0 if count == "0" else -1)
        elif line.startswith("-"):
            old_line += 1
            removed.add(old_line)
        elif line.startswith("+"):
            inserted_after.add(old_line)
        elif line.startswith(" "):
            old_line += 1
    return removed, inserted_after


def touches_guarded_region(base_text: str, file_diff: str) -> bool:
    """True when a change removes, edits or inserts lines inside a guarded region of the base.

    Unpaired markers on the base guard the whole file, so a broken marker never opens it.
    """
    if GUARD_START not in base_text and GUARD_END not in base_text:
        return False
    regions = guarded_regions(base_text)
    removed, inserted_after = _old_lines_touched(file_diff)
    if regions is None:
        return bool(removed or inserted_after)
    return any(start <= n <= end for start, end in regions for n in removed) or any(
        start <= n < end for start, end in regions for n in inserted_after
    )


def frozen_paths(preregistration: str) -> list[str]:
    """The path patterns `config/preregistration.json` freezes, or [] while it isn't frozen.

    >>> frozen_paths('{"frozen": true, "paths": ["usecases/", "data/*/gold.jsonl"]}')
    ['usecases/', 'data/*/gold.jsonl']
    >>> frozen_paths('{"frozen": false, "paths": ["usecases/"]}')
    []
    """
    data = json.loads(preregistration)
    return list(data.get("paths", [])) if data.get("frozen") is True else []


def matches_frozen(path: str, patterns: list[str]) -> bool:
    """A directory pattern (`usecases/`) covers everything under it; others are globs.

    >>> matches_frozen("data/tenders/gold.jsonl", ["data/*/gold.jsonl"])
    True
    >>> matches_frozen("usecases/tenders/prompt.md", ["usecases/"])
    True
    """
    return any(path.startswith(p) if p.endswith("/") else fnmatch(path, p) for p in patterns)


# Lines `.gitignore` must always hold, so `.env` and private context can never be staged
# by accident. No edit, commit, push or merge may remove one (protect_files.py and the
# guard). Keep in sync with .gitignore.
REQUIRED_IGNORES = (
    ".env",
    ".env.*",
    "!.env.example",
    ".private/",
    "CLAUDE.local.md",
    ".autopilot/",
)


def missing_ignores(gitignore: str) -> list[str]:
    """The required lines a `.gitignore` text lacks.

    >>> missing_ignores(".env\\n.env.*\\n!.env.example\\n.private/\\nCLAUDE.local.md\\n")
    ['.autopilot/']
    """
    present = {line.strip() for line in gitignore.splitlines()}
    return [line for line in REQUIRED_IGNORES if line not in present]


def gitignore_findings(removed: str, added: str, where: str) -> list[Finding]:
    """A change that removes a required `.gitignore` line without adding it back."""
    gone = {ln.strip() for ln in removed.splitlines()} - {ln.strip() for ln in added.splitlines()}
    return [
        Finding(where, "gitignore", f"removes the required ignore line `{line}`")
        for line in REQUIRED_IGNORES
        if line in gone
    ]


def is_guardrail_path(path: str) -> bool:
    return any(path == g or (g.endswith("/") and path.startswith(g)) for g in GUARDRAIL_PATHS)


# --- Secrets -----------------------------------------------------------------------------

# Provider key shapes. gitleaks covers many more; these are the ones this project could
# plausibly hold, checked even where gitleaks isn't installed.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("sk- style API key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)
# A secret-named variable assigned a long literal. The value must mix letters and digits
# and contain no dot, `$`, brace or bracket, so references (`os.environ[...]`,
# `${{ secrets.X }}`, `config.api_key_env`) and empty template values never match.
_ASSIGNMENT = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD)\b['\"]?\s*[:=]\s*['\"]?"
    r"(?P<value>[A-Za-z0-9_\-+/=]{20,})"
)


def _secret_hits(line: str) -> list[str]:
    hits = [name for name, pattern in _SECRET_PATTERNS if pattern.search(line)]
    for match in _ASSIGNMENT.finditer(line):
        value = match.group("value")
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            hits.append("secret-named assignment")
    return hits


# --- Personal data -----------------------------------------------------------------------

_HOME_PATH = re.compile(
    r"(?<![\w.-])/(?:Users|home)/(?!runner/)[A-Za-z0-9._-]+/|\b[A-Za-z]:\\Users\\[A-Za-z0-9._-]+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_ALLOWED_EMAILS = {"noreply@anthropic.com", "noreply@github.com", "git@github.com"}
_ALLOWED_EMAIL_DOMAINS = ("users.noreply.github.com", "example.com", "example.org", "example.net")
# Public source documents may carry a buyer's published contact address.
_EMAIL_EXEMPT_PREFIXES = ("data/", "cache/llm/")


def _email_allowed(email: str, domain: str) -> bool:
    domain = domain.lower()
    return (
        email.lower() in _ALLOWED_EMAILS
        or domain.endswith(_ALLOWED_EMAIL_DOMAINS)
        or domain.endswith(".test")
        or domain.endswith(".invalid")
    )


def _personal_hits(line: str, path: str | None) -> list[str]:
    hits = []
    if _HOME_PATH.search(line):
        hits.append("absolute home-directory path (use a repo-relative path or ~)")
    if path is None or not path.startswith(_EMAIL_EXEMPT_PREFIXES):
        for match in _EMAIL.finditer(line):
            if not _email_allowed(match.group(0), match.group("domain")):
                hits.append("email address (use a noreply or example.com address)")
                break
    return hits


# --- Private terms -----------------------------------------------------------------------


def load_terms(text: str) -> list[re.Pattern[str]]:
    """Parse a denylist: one literal term per line, `re:` for a regex, `#` for comments.

    >>> [p.pattern for p in load_terms("# c\\nfoo.bar\\nre:ba+z\\n")]
    ['foo\\\\.bar', 'ba+z']
    """
    terms = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        source = line[3:] if line.startswith("re:") else re.escape(line)
        terms.append(re.compile(source, re.IGNORECASE))
    return terms


# --- Scanning ----------------------------------------------------------------------------


def scan_text(
    text: str,
    where: str,
    terms: list[re.Pattern[str]],
    *,
    path: str | None = None,
    personal: bool = True,
) -> list[Finding]:
    """Every secret, personal-data and private-term finding in `text`, by line."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        at = f"{where}:{number}"
        findings += [Finding(at, "secret", name) for name in _secret_hits(line)]
        if personal:
            findings += [Finding(at, "personal-data", d) for d in _personal_hits(line, path)]
        for term in terms:
            if term.search(line):
                findings.append(Finding(at, "private-term", f"matches {term.pattern!r}"))
    return findings


def removed_lines_by_file(diff: str) -> dict[str, str]:
    """The removed lines of a unified diff, joined per source file.

    >>> removed_lines_by_file("--- a/.gitignore\\n+++ b/.gitignore\\n@@ -1 +0,0 @@\\n-.env\\n")
    {'.gitignore': '.env'}
    """
    files: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            source = line[4:]
            current = None if source == "/dev/null" else files.setdefault(source[2:], [])
        elif line.startswith("+++ "):
            continue
        elif line.startswith("-") and current is not None:
            current.append(line[1:])
    return {name: "\n".join(lines) for name, lines in files.items()}


def added_lines_by_file(diff: str) -> dict[str, str]:
    """The added lines of a unified diff, joined per destination file.

    >>> added_lines_by_file("+++ b/a.py\\n@@ -0,0 +1 @@\\n+x = 1\\n-y\\n")
    {'a.py': 'x = 1'}
    """
    files: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = None if target == "/dev/null" else files.setdefault(target[2:], [])
        elif line.startswith("+") and current is not None:
            current.append(line[1:])
    return {name: "\n".join(lines) for name, lines in files.items()}


# --- Commit metadata ---------------------------------------------------------------------

_CONVENTIONAL = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|chore|ci|build|revert)(\([a-z0-9,./_-]+\))?!?: \S.*"
)


def check_commit_subject(subject: str) -> str | None:
    """Why a commit or PR title breaks the Conventional Commits form, or None.

    >>> check_commit_subject("feat(core): add the ledger") is None
    True
    >>> check_commit_subject("Update stuff")
    'not a Conventional Commit subject (`type(scope): change`)'
    """
    if subject.startswith(("fixup! ", "squash! ")):
        return None  # squashed away before main
    if not _CONVENTIONAL.match(subject):
        return "not a Conventional Commit subject (`type(scope): change`)"
    return None


def check_author_email(email: str) -> str | None:
    """Commits in a public repo carry only noreply identities."""
    if email.lower().endswith("@users.noreply.github.com") or email.lower() == "noreply@github.com":
        return None
    return "not a GitHub noreply address (set `git config user.email <id>+<login>@users.noreply.github.com`)"


# --- Review requirements -----------------------------------------------------------------

# Keep in sync with the agents in .claude/agents/ and the gate table in CLAUDE.md.
REVIEW_AGENTS = (
    "code-reviewer",
    "security-reviewer",
    "coherence-auditor",
    "determinism-auditor",
    "test-reviewer",
)
DEPENDABOT = "dependabot[bot]"


def approved_on_head(reviews: list[dict[str, str]], *, owner: str, head: str) -> bool:
    """True when the owner's latest review approves exactly the head commit.

    `reviews` are in submission order, each `{"login", "state", "commit"}`. A later push
    moves the head, so an approval of an older commit no longer counts, as GitHub's own
    "dismiss stale approvals" would do.

    >>> approved_on_head([{"login": "me", "state": "APPROVED", "commit": "abc"}], owner="me", head="abc")
    True
    >>> approved_on_head([{"login": "me", "state": "APPROVED", "commit": "old"}], owner="me", head="abc")
    False
    """
    own = [r for r in reviews if r["login"] == owner and r["state"] != "COMMENTED"]
    return bool(own) and own[-1]["state"] == "APPROVED" and own[-1]["commit"] == head


def is_docs_only(paths: list[str]) -> bool:
    """Prose only: Markdown outside `.claude/` (agent and skill files are configuration)."""
    return bool(paths) and all(p.endswith(".md") and not p.startswith(".claude/") for p in paths)


def required_reviews(paths: list[str], *, author: str, phase_exit: bool) -> set[str]:
    """The review agents whose report a PR needs before the merge gate accepts it.

    >>> sorted(required_reviews(["README.md"], author="me", phase_exit=False))
    ['coherence-auditor']
    >>> sorted(required_reviews(["uv.lock"], author="dependabot[bot]", phase_exit=False))
    ['security-reviewer']
    """
    if author == DEPENDABOT:
        return {"security-reviewer"}
    agents = (
        {"coherence-auditor"} if is_docs_only(paths) else {"code-reviewer", "security-reviewer"}
    )
    if phase_exit:
        agents |= {"coherence-auditor", "determinism-auditor", "test-reviewer"}
    return agents
