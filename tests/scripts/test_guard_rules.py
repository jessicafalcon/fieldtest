"""The pure rules: what never reaches the public repo, and what a PR needs to merge."""

from __future__ import annotations

import pytest
from guard_rules import (
    added_lines_by_file,
    check_author_email,
    check_commit_subject,
    diffs_by_file,
    forbidden_path,
    frozen_paths,
    is_guardrail_path,
    load_terms,
    matches_frozen,
    required_reviews,
    scan_text,
    touches_guarded_region,
)

from tests.conftest import (
    FAKE_API_KEY,
    FAKE_ASSIGNMENT,
    FAKE_GITHUB_TOKEN,
    HOME_PATH,
    PERSONAL_EMAIL,
)


@pytest.mark.parametrize(
    "path",
    [
        ".private/notes.md",
        ".private/denylist.txt",
        ".env",
        ".env.local",
        "config/.env.production",
        "CLAUDE.local.md",
        ".claude/settings.local.json",
        "deploy/server.pem",
        "id_ed25519",
    ],
)
def test_private_and_secret_paths_are_forbidden(path: str) -> None:
    assert forbidden_path(path) is not None


@pytest.mark.parametrize(
    "path", [".env.example", "README.md", "src/fieldtest/core/env.py", "docs/adr/0001-x.md"]
)
def test_ordinary_paths_are_allowed(path: str) -> None:
    assert forbidden_path(path) is None


@pytest.mark.parametrize("secret", [FAKE_API_KEY, FAKE_GITHUB_TOKEN, FAKE_ASSIGNMENT])
def test_secrets_are_found_without_echoing_them(secret: str) -> None:
    findings = scan_text(f"x = 1\n{secret}\n", "f.py", [])
    assert [(f.where, f.rule) for f in findings][:1] == [("f.py:2", "secret")]
    assert all(secret not in str(f) for f in findings)


@pytest.mark.parametrize(
    "line",
    [
        "api_key = os.environ['MISTRAL_API_KEY']",
        "MISTRAL_API_KEY=",
        "token: ${{ secrets.GITHUB_TOKEN }}",
        "api_key = config.provider_api_key_from_environment",
        "secret_scanning_push_protection",
    ],
)
def test_references_to_secrets_are_not_secrets(line: str) -> None:
    assert scan_text(line, "f", []) == []


def test_home_paths_and_personal_emails_are_personal_data() -> None:
    findings = scan_text(f"see {HOME_PATH}\nmail {PERSONAL_EMAIL}\n", "doc.md", [])
    assert [f.rule for f in findings] == ["personal-data", "personal-data"]


@pytest.mark.parametrize(
    "text",
    [
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "1+someone@users.noreply.github.com",
        "contact@example.com",
        "uses: actions/checkout@v7.0.1",
        "~/dev/fieldtest and /home/runner/work",
    ],
)
def test_noreply_example_and_tool_strings_pass(text: str) -> None:
    assert scan_text(text, "f", []) == []


def test_public_source_documents_may_carry_contact_emails() -> None:
    assert scan_text(PERSONAL_EMAIL, "d", [], path="data/tenders/raw/1.txt") == []
    assert scan_text(PERSONAL_EMAIL, "d", [], path="docs/x.md") != []


def test_terms_are_literal_case_insensitive_or_regex() -> None:
    terms = load_terms("# comment\nsecret.project\nre:code ?name\n")
    hits = scan_text("The SECRET.PROJECT and codename\nsecretXproject\n", "f", terms)
    assert [(f.where, f.rule) for f in hits] == [("f:1", "private-term"), ("f:1", "private-term")]


def test_personal_data_check_can_be_skipped_for_command_text() -> None:
    assert scan_text(HOME_PATH, "command", [], personal=False) == []


def test_added_lines_ignore_removed_and_deleted_files() -> None:
    diff = (
        "+++ b/keep.py\n@@ -1 +1 @@\n-old\n+new\n"
        "+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
        "+++ b/two.md\n@@ -0,0 +1,2 @@\n+a\n+b\n"
    )
    assert added_lines_by_file(diff) == {"keep.py": "new", "two.md": "a\nb"}


@pytest.mark.parametrize(
    "subject",
    [
        "feat(core): add the ledger",
        "fix(guard,ci)!: x",
        "docs: y",
        "build(deps): bump z",
        "fixup! feat: x",
    ],
)
def test_conventional_subjects_pass(subject: str) -> None:
    assert check_commit_subject(subject) is None


@pytest.mark.parametrize("subject", ["Update README", "feat:no space", "wip", "Feat: x", ""])
def test_other_subjects_fail(subject: str) -> None:
    assert check_commit_subject(subject) is not None


def test_only_noreply_identities_may_author() -> None:
    assert check_author_email("1+me@users.noreply.github.com") is None
    assert check_author_email("noreply@github.com") is None
    assert check_author_email(PERSONAL_EMAIL) is not None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".claude/hooks/bash_policy.py", True),
        (".claude/settings.json", True),
        (".github/workflows/ci.yml", True),
        ("scripts/guard.py", True),
        (".claude/agents/merge-gate.md", True),
        (".gitignore", True),
        (".github/loop-identity.json", True),
        ("scripts/loop_auth.py", True),
        (".claude/agents/code-reviewer.md", True),
        (".claude/agents/plan-arbiter.md", True),
        (".claude/skills/autopilot/SKILL.md", True),
        (".claude/sandbox.autopilot.json", True),
        ("config/preregistration.json", True),
        (".claude/skills/fieldtest-craft/SKILL.md", False),
        ("scripts/check_records.py", False),
        ("README.md", False),
    ],
)
def test_guardrail_paths(path: str, expected: bool) -> None:
    assert is_guardrail_path(path) is expected


def test_reviews_scale_with_the_change() -> None:
    docs = required_reviews(["README.md", "docs/PROGRESS.md"], author="me", phase_exit=False)
    assert docs == {"coherence-auditor"}
    # Agent and skill definitions are configuration, not prose.
    config = required_reviews([".claude/agents/x.md"], author="me", phase_exit=False)
    assert config == {"code-reviewer", "security-reviewer"}
    phase_exit = required_reviews(["src/fieldtest/x.py"], author="me", phase_exit=True)
    assert phase_exit == {
        "code-reviewer",
        "security-reviewer",
        "coherence-auditor",
        "determinism-auditor",
        "test-reviewer",
    }


BASE = "intro\n<!-- guarded:start -->\nrule one\nrule two\n<!-- guarded:end -->\nfree text\n"


def file_diff(header: str, *lines: str) -> str:
    return "\n".join([header, *lines])


@pytest.mark.parametrize(
    ("hunk", "touched"),
    [
        (file_diff("@@ -3 +3 @@", "-rule one", "+rule 1"), True),  # edits inside
        (file_diff("@@ -3,0 +4 @@", "+rule three"), True),  # inserts inside
        (file_diff("@@ -5 +4,0 @@", "-<!-- guarded:end -->"), True),  # removes a marker
        (file_diff("@@ -6 +6 @@", "-free text", "+freer text"), False),
        (file_diff("@@ -5,0 +6 @@", "+appended after the region"), False),
        (
            file_diff(
                "@@ -1,3 +1,3 @@", " intro", " <!-- guarded:start -->", "-rule one", "+rule 1"
            ),
            True,
        ),
    ],
)
def test_guarded_regions_catch_edits_inside_and_nothing_outside(hunk: str, touched: bool) -> None:
    assert touches_guarded_region(BASE, hunk) is touched


def test_unpaired_markers_guard_the_whole_file() -> None:
    broken = "<!-- guarded:start -->\nrule\nfree\n"
    assert touches_guarded_region(broken, file_diff("@@ -3 +3 @@", "-free", "+x"))


def test_files_without_markers_are_never_guarded() -> None:
    assert not touches_guarded_region("plain\n", file_diff("@@ -1 +1 @@", "-plain", "+x"))


def test_diffs_split_per_file_by_old_path() -> None:
    diff = (
        "diff --git a/A.md b/A.md\n--- a/A.md\n+++ b/A.md\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/new.md b/new.md\n--- /dev/null\n+++ b/new.md\n@@ -0,0 +1 @@\n+n\n"
    )
    assert diffs_by_file(diff) == {"A.md": "@@ -1 +1 @@\n-a\n+b", "new.md": "@@ -0,0 +1 @@\n+n"}


def test_preregistration_freezes_only_once_frozen() -> None:
    patterns = frozen_paths('{"frozen": true, "paths": ["usecases/", "data/*/gold.jsonl"]}')
    assert matches_frozen("usecases/tenders/config.yaml", patterns)
    assert matches_frozen("data/tenders/gold.jsonl", patterns)
    assert not matches_frozen("data/tenders/raw/1.txt", patterns)
    assert frozen_paths('{"frozen": false, "paths": ["usecases/"]}') == []
