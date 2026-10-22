"""The guard blocks what must not be published, in every mode, and passes clean work."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from guard import evaluate_pr, flag_values, hook_texts, run_base_guard_if_modified

from tests.conftest import (
    FAKE_API_KEY,
    HOME_PATH,
    NOREPLY,
    PERSONAL_EMAIL,
    ROOT,
    git,
)

GUARD = ROOT / "scripts" / "guard.py"


def run_guard(
    repo: Path, *args: str, stdin: str = "", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(repo), **(env or {})},
        check=False,
    )


# --- The brief's Phase 0A acceptance cases ---------------------------------------------


def test_a_commit_with_a_fake_api_key_is_blocked(repo: Path) -> None:
    (repo / "config.py").write_text(f'KEY = "{FAKE_API_KEY}"\n')
    git(repo, "add", "config.py")
    result = run_guard(repo, "--staged")
    assert result.returncode == 1
    assert "[secret]" in result.stderr
    assert FAKE_API_KEY not in result.stderr


def test_a_commit_staging_a_private_file_is_blocked(repo: Path) -> None:
    (repo / ".private").mkdir()
    (repo / ".private" / "notes.md").write_text("private\n")
    git(repo, "add", "-f", ".private/notes.md")
    result = run_guard(repo, "--staged")
    assert result.returncode == 1
    assert "[private-path]" in result.stderr


def test_a_staged_env_file_is_blocked(repo: Path) -> None:
    (repo / ".env").write_text("X=1\n")
    git(repo, "add", "-f", ".env")
    assert run_guard(repo, "--staged").returncode == 1


def test_a_denylisted_term_is_blocked_and_clean_work_passes(repo: Path) -> None:
    (repo / ".private").mkdir()
    (repo / ".private" / "denylist.txt").write_text("codename zephyr\n")
    (repo / "notes.md").write_text("Built for Codename Zephyr.\n")
    git(repo, "add", "notes.md")
    assert run_guard(repo, "--staged").returncode == 1
    (repo / "notes.md").write_text("A neutral description.\n")
    git(repo, "add", "notes.md")
    assert run_guard(repo, "--staged").returncode == 0


# --- Commit messages and ranges ------------------------------------------------------------


def test_commit_messages_need_the_conventional_form_and_no_personal_data(repo: Path) -> None:
    message = repo / "MSG"
    message.write_text("feat(core): add x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
    assert run_guard(repo, "--commit-msg", str(message)).returncode == 0
    message.write_text(f"feat: add x\n\nwritten at {HOME_PATH}\n")
    assert run_guard(repo, "--commit-msg", str(message)).returncode == 1
    message.write_text("Added stuff\n")
    assert run_guard(repo, "--commit-msg", str(message)).returncode == 1


def test_a_range_rejects_a_personal_author_email(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "a.md").write_text("a\n")
    git(repo, "add", "a.md")
    git(repo, "-c", f"user.email={PERSONAL_EMAIL}", "commit", "-q", "-m", "docs: add a")
    result = run_guard(repo, "--range", f"{base}..HEAD")
    assert result.returncode == 1
    assert "[author-email]" in result.stderr


def test_a_secret_added_then_removed_inside_a_range_is_still_caught(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "k.py").write_text(f'K = "{FAKE_API_KEY}"\n')
    git(repo, "add", "k.py")
    git(repo, "commit", "-q", "-m", "feat: add k")
    (repo / "k.py").write_text("K = None\n")
    git(repo, "commit", "-q", "-am", "fix: drop k")
    assert run_guard(repo, "--range", f"{base}..HEAD").returncode == 1


def test_ci_range_applies_the_pr_rules(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "docs").mkdir()
    (repo / "docs" / "PROGRESS.md").write_text("status\n")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "ci: add ci")
    head = git(repo, "rev-parse", "HEAD").strip()
    reviews = repo.parent / "reviews.json"

    def ci(*review: tuple[str, str, str]) -> subprocess.CompletedProcess[str]:
        rest = [{"user": {"login": u}, "state": st, "commit_id": c} for u, st, c in review]
        reviews.write_text(json.dumps(rest))
        env = {
            "FIELDTEST_PR_AUTHOR": "loop[bot]",
            "FIELDTEST_OWNER": "owner",
            "FIELDTEST_PR_REVIEWS": str(reviews),
        }
        return run_guard(repo, "--range", f"{base}..HEAD", env=env)

    unapproved = ci()
    assert unapproved.returncode == 1
    assert "[guardrail-change]" in unapproved.stderr
    assert ci(("loop[bot]", "APPROVED", head)).returncode == 1  # only the owner approves
    assert ci(("owner", "APPROVED", "0" * 40)).returncode == 1  # an older commit
    assert ci(("owner", "APPROVED", head)).returncode == 0


def test_removing_a_required_gitignore_line_is_blocked_in_every_mode(repo: Path) -> None:
    (repo / ".gitignore").write_text(
        ".env\n.env.*\n!.env.example\n.private/\nCLAUDE.local.md\n.autopilot/\n"
    )
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "chore: ignore secrets")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / ".gitignore").write_text(".private/\nCLAUDE.local.md\n.autopilot/\nruns/\n")
    git(repo, "add", ".gitignore")
    staged = run_guard(repo, "--staged")
    assert staged.returncode == 1
    assert "[gitignore]" in staged.stderr
    git(repo, "commit", "-q", "-m", "chore: tidy ignores")
    assert run_guard(repo, "--range", f"{base}..HEAD").returncode == 1
    git(repo, "rm", "-q", ".gitignore")  # deleting the file removes every line
    assert run_guard(repo, "--staged").returncode == 1


# --- Hook mode ------------------------------------------------------------------------------


def hook(repo: Path, tool: str, tool_input: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}
    return run_guard(repo, "--hook", stdin=json.dumps(payload))


def test_hook_blocks_writing_a_secret_into_the_repo_only(repo: Path, tmp_path: Path) -> None:
    content = f"KEY = '{FAKE_API_KEY}'\n"
    assert (
        hook(repo, "Write", {"file_path": str(repo / "x.py"), "content": content}).returncode == 2
    )
    outside = tmp_path / "scratch.txt"
    assert hook(repo, "Write", {"file_path": str(outside), "content": content}).returncode == 0


def test_hook_checks_edits_and_multiedits(repo: Path) -> None:
    edit = {"file_path": str(repo / "a.md"), "old_string": "a", "new_string": PERSONAL_EMAIL}
    assert hook(repo, "Edit", edit).returncode == 2
    multi = {
        "file_path": str(repo / "a.md"),
        "edits": [{"old_string": "a", "new_string": HOME_PATH}],
    }
    assert hook(repo, "MultiEdit", multi).returncode == 2


def test_hook_reads_pr_bodies_from_files_and_heredocs(repo: Path) -> None:
    body = repo / "body.md"
    body.write_text(f"reach me at {PERSONAL_EMAIL}\n")
    command = f"gh pr create --title 'docs: x' --body-file {body}"
    assert hook(repo, "Bash", {"command": command}).returncode == 2
    heredoc = f"git commit -F - <<'EOF'\nfeat: x\n\n{HOME_PATH}\nEOF"
    assert hook(repo, "Bash", {"command": heredoc}).returncode == 2
    clean = "git commit -F - <<'EOF'\nfeat: add `x` to the docs\nEOF"
    assert hook(repo, "Bash", {"command": clean}).returncode == 0


def test_hook_fails_closed_on_text_it_cannot_see(repo: Path) -> None:
    for command in (
        "gh pr create --body-file missing.md",
        'gh pr comment 1 --body "$(cat notes.txt)"',
        "echo x | gh pr create -F -",
        "git commit -F - <<EOF\nfeat: `whoami`\nEOF",
    ):
        assert hook(repo, "Bash", {"command": command}).returncode == 2, command


def test_hook_ignores_commands_that_publish_nothing(repo: Path) -> None:
    assert hook(repo, "Bash", {"command": f"ls {HOME_PATH}"}).returncode == 0


def test_local_paths_in_the_command_itself_are_not_personal_data(repo: Path) -> None:
    body = repo / "b.md"
    body.write_text("A neutral body.\n")
    texts = hook_texts(
        "Bash", {"command": f"cd {repo} && gh pr create -t 'docs: x' -F {body}"}, repo, repo
    )
    assert [(where, personal) for where, _, personal in texts] == [
        ("command", False),
        ("message", True),
        (str(body), True),
    ]


def test_flag_values_reads_every_form() -> None:
    command = 'gh pr create -t "use -F x" --body-file=b.md -Fc.md -dF d.md'
    assert flag_values(command, ("-F", "--body-file")) == ["b.md", "c.md", "d.md"]


# --- PR mode: what the merge gate relies on -----------------------------------------------


OWNER = "owner"
BOT = "fieldtest-loop[bot]"
HEAD = "b" * 40


def pr(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "number": 7,
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "isCrossRepository": False,
        "author": {"login": OWNER},
        "title": "feat(core): add the ledger",
        "body": "Summary.",
        "files": [{"path": "src/fieldtest/core/ledger.py"}, {"path": "docs/PROGRESS.md"}],
        "commits": [
            {
                "oid": HEAD,
                "authors": [{"email": NOREPLY}],
                "messageHeadline": "feat: x",
                "messageBody": "",
            }
        ],
        "reviews": [],
        "statusCheckRollup": [
            {"name": "check", "conclusion": "SUCCESS"},
            {"name": "security", "conclusion": "SUCCESS"},
        ],
        "mergeable": "MERGEABLE",
        "comments": [
            review("code-reviewer", "ready", HEAD),
            review("security-reviewer", "ready", HEAD),
        ],
        "headRefOid": HEAD,
    }
    base.update(overrides)
    return base


def review(agent: str, verdict: str, sha: str, author: str = OWNER) -> dict[str, Any]:
    marker = f"<!-- fieldtest-review agent={agent} verdict={verdict} sha={sha} -->"
    return {"author": {"login": author}, "body": f"{marker}\n**Verdict:** {verdict}"}


def rules(found: list[Any]) -> set[str]:
    return {f.rule for f in found}


def test_a_clean_reviewed_green_pr_passes() -> None:
    found, notes = evaluate_pr(pr(), "", owner=OWNER, bot=BOT, terms=[])
    assert found == []
    assert len(notes) == 2


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"isCrossRepository": True}, "fork"),
        ({"author": {"login": "stranger"}}, "author"),
        ({"baseRefName": "dev"}, "base"),
        ({"isDraft": True}, "state"),
        ({"title": "Add ledger"}, "commit-message"),
        ({"statusCheckRollup": [{"name": "check", "conclusion": "SUCCESS"}]}, "checks"),
        (
            {
                "statusCheckRollup": [
                    {"name": "check", "conclusion": "FAILURE"},
                    {"name": "security", "conclusion": "SUCCESS"},
                ]
            },
            "checks",
        ),
        ({"mergeable": "CONFLICTING"}, "mergeable"),
        ({"files": [{"path": "src/fieldtest/x.py"}]}, "records"),
        (
            {"files": [{"path": ".claude/hooks/bash_policy.py"}, {"path": "docs/PROGRESS.md"}]},
            "guardrail-change",
        ),
        ({"files": [{"path": ".env"}, {"path": "docs/PROGRESS.md"}]}, "private-path"),
        ({"body": f"Ping {PERSONAL_EMAIL}"}, "personal-data"),
    ],
)
def test_each_merge_rule_blocks(overrides: dict[str, Any], rule: str) -> None:
    found, _ = evaluate_pr(pr(**overrides), "", owner=OWNER, bot=BOT, terms=[])
    assert rule in rules(found)


def test_a_secret_in_the_diff_blocks() -> None:
    diff = f"+++ b/x.py\n@@ -0,0 +1 @@\n+K = '{FAKE_API_KEY}'\n"
    found, _ = evaluate_pr(pr(), diff, owner=OWNER, bot=BOT, terms=[])
    assert "secret" in rules(found)


def test_reviews_from_anyone_but_the_owner_do_not_count() -> None:
    comments = [
        review("code-reviewer", "ready", HEAD, author="stranger"),
        review("security-reviewer", "ready", HEAD),
    ]
    found, notes = evaluate_pr(pr(comments=comments), "", owner=OWNER, bot=BOT, terms=[])
    assert any("code-reviewer" in f.detail for f in found)
    assert len(notes) == 1  # the stranger's text never reaches the gate


def test_not_ready_blocks_and_fixes_after_a_review_need_a_fix_log() -> None:
    first = "a" * 40
    commits = [
        {
            "oid": first,
            "authors": [{"email": NOREPLY}],
            "messageHeadline": "feat: x",
            "messageBody": "",
        },
        {
            "oid": HEAD,
            "authors": [{"email": NOREPLY}],
            "messageHeadline": "fix: y",
            "messageBody": "",
        },
    ]
    not_ready = [
        review("code-reviewer", "not-ready", HEAD),
        review("security-reviewer", "ready", HEAD),
    ]
    found, _ = evaluate_pr(
        pr(commits=commits, comments=not_ready), "", owner=OWNER, bot=BOT, terms=[]
    )
    assert any("not-ready" in f.detail for f in found)

    stale = [
        review("code-reviewer", "ready-after-fixes", first),
        review("security-reviewer", "ready", HEAD),
    ]
    found, _ = evaluate_pr(pr(commits=commits, comments=stale), "", owner=OWNER, bot=BOT, terms=[])
    assert any("fix log" in f.detail for f in found)

    fixlog = {"author": {"login": OWNER}, "body": f"<!-- fieldtest-fixlog sha={HEAD} -->\n1. fixed"}
    found, _ = evaluate_pr(
        pr(commits=commits, comments=[*stale, fixlog]), "", owner=OWNER, bot=BOT, terms=[]
    )
    assert found == []


def test_docs_only_prs_need_the_coherence_auditor() -> None:
    files = [{"path": "README.md"}, {"path": "docs/PROGRESS.md"}]
    found, _ = evaluate_pr(pr(files=files, comments=[]), "", owner=OWNER, bot=BOT, terms=[])
    assert {f.detail for f in found} == {"no report from `coherence-auditor`"}


@pytest.mark.parametrize("login", ["dependabot[bot]", "app/dependabot"])
def test_dependabot_prs_need_only_the_security_review_and_no_progress_record(login: str) -> None:
    bot = {"login": login}
    files = [{"path": "uv.lock"}]
    comments = [review("security-reviewer", "ready", HEAD)]
    found, _ = evaluate_pr(
        pr(author=bot, files=files, comments=comments, title="build(deps): bump x"),
        "",
        owner=OWNER,
        bot=BOT,
        terms=[],
    )
    assert found == []


def test_the_loop_authors_prs_and_its_review_comments_count() -> None:
    loop = {"login": BOT}
    comments = [
        review("code-reviewer", "ready", HEAD, author=BOT),
        review("security-reviewer", "ready", HEAD, author=BOT),
    ]
    found, notes = evaluate_pr(
        pr(author=loop, comments=comments), "", owner=OWNER, bot=BOT, terms=[]
    )
    assert found == []
    assert len(notes) == 2


def test_a_co_author_trailer_is_message_text_not_the_commit_identity() -> None:
    # gh lists `Co-authored-by` trailers as authors after the commit's own author.
    trailer = "Co-Authored-By: Claude <noreply@anthropic.com>"
    commit = {
        "oid": HEAD,
        "authors": [{"email": NOREPLY}, {"email": "noreply@anthropic.com"}],
        "messageHeadline": "feat: x",
        "messageBody": trailer,
    }
    found, _ = evaluate_pr(pr(commits=[commit]), "", owner=OWNER, bot=BOT, terms=[])
    assert found == []
    commit["authors"] = [{"email": PERSONAL_EMAIL}, {"email": NOREPLY}]
    found, _ = evaluate_pr(pr(commits=[commit]), "", owner=OWNER, bot=BOT, terms=[])
    assert "author-email" in rules(found)


def test_the_loop_is_recognised_in_the_login_shapes_gh_returns() -> None:
    # Recorded from `gh pr view --json author,comments` on a PR the loop's App opened: the
    # author is `app/<slug>` and comment authors are `<slug>`, while the loop's identity
    # file and CI's event payload hold `<slug>[bot]`.
    loop = {"is_bot": True, "login": "app/fieldtest-loop"}
    comments = [
        review("code-reviewer", "ready", HEAD, author="fieldtest-loop"),
        review("security-reviewer", "ready", HEAD, author="fieldtest-loop"),
    ]
    found, notes = evaluate_pr(
        pr(author=loop, comments=comments), "", owner=OWNER, bot=BOT, terms=[]
    )
    assert found == []
    assert len(notes) == 2


def test_a_lookalike_login_is_not_the_loop() -> None:
    comments = [
        review("code-reviewer", "ready", HEAD, author="fieldtest-loop-x"),
        review("security-reviewer", "ready", HEAD, author="fieldtest-loop-x"),
    ]
    found, _ = evaluate_pr(
        pr(author={"login": "app/fieldtest-loop-x"}, comments=comments),
        "",
        owner=OWNER,
        bot=BOT,
        terms=[],
    )
    assert {"author", "review"} <= rules(found)


def test_a_guardrail_pr_merges_only_with_the_owners_approval_of_its_head() -> None:
    files = [{"path": "scripts/guard.py"}, {"path": "docs/PROGRESS.md"}]

    def rules_with(*reviews: tuple[str, str, str]) -> set[str]:
        raw = [{"author": {"login": u}, "state": st, "commit": {"oid": c}} for u, st, c in reviews]
        found, _ = evaluate_pr(
            pr(author={"login": BOT}, files=files, reviews=raw), "", owner=OWNER, bot=BOT, terms=[]
        )
        return rules(found)

    assert "guardrail-change" in rules_with()
    assert "guardrail-change" in rules_with((BOT, "APPROVED", HEAD))
    assert "guardrail-change" in rules_with((OWNER, "APPROVED", "a" * 40))
    assert "guardrail-change" in rules_with(
        (OWNER, "APPROVED", HEAD), (OWNER, "CHANGES_REQUESTED", HEAD)
    )
    assert "guardrail-change" not in rules_with(
        (OWNER, "APPROVED", HEAD), (OWNER, "COMMENTED", HEAD)
    )


def test_a_guarded_region_or_frozen_path_needs_the_owners_approval() -> None:
    base_files = {
        "PROJECT-BRIEF.md": "x\n<!-- guarded:start -->\n- **Acceptance:** 100%\n<!-- guarded:end -->\n",
        "config/preregistration.json": '{"frozen": true, "paths": ["usecases/"]}',
    }
    diff = (
        "diff --git a/PROJECT-BRIEF.md b/PROJECT-BRIEF.md\n--- a/PROJECT-BRIEF.md\n"
        "+++ b/PROJECT-BRIEF.md\n@@ -3 +3 @@\n-- **Acceptance:** 100%\n+- **Acceptance:** 80%\n"
    )
    files = [
        {"path": "PROJECT-BRIEF.md"},
        {"path": "usecases/t/config.yaml"},
        {"path": "docs/PROGRESS.md"},
    ]
    found, _ = evaluate_pr(
        pr(files=files), diff, owner=OWNER, bot=BOT, terms=[], read_base=base_files.get
    )
    detail = next(f.detail for f in found if f.rule == "guardrail-change")
    assert "a guarded region of PROJECT-BRIEF.md" in detail
    assert "usecases/t/config.yaml (frozen by pre-registration)" in detail
    approval = [{"author": {"login": OWNER}, "state": "APPROVED", "commit": {"oid": HEAD}}]
    found, _ = evaluate_pr(
        pr(files=files, reviews=approval),
        diff,
        owner=OWNER,
        bot=BOT,
        terms=[],
        read_base=base_files.get,
    )
    assert "guardrail-change" not in rules(found)


# --- Main's guard judges a PR: fail closed when main can't be read ------------------------


def test_before_the_first_merge_a_pr_is_judged_by_its_own_guard(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FIELDTEST_GUARD_IS_BASE", raising=False)
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    assert run_base_guard_if_modified(repo, ["--pr", "1"]) is None


def test_an_unreachable_origin_blocks_instead_of_trusting_the_prs_guard(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FIELDTEST_GUARD_IS_BASE", raising=False)
    git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))
    assert run_base_guard_if_modified(repo, ["--pr", "1"]) == 1
