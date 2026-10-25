"""The loop's sandbox keeps its safety properties: no way out, no key in sight, no reads of
secrets, and the driver always passes it (ADR 0005)."""

from __future__ import annotations

import json
import subprocess
import tomllib
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from guard_rules import GUARDRAIL_PATHS
from render_sandbox import render

from tests.conftest import ROOT

TEMPLATE = ROOT / ".claude" / "sandbox.autopilot.json"


def settings() -> dict[str, Any]:
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_sandbox_cannot_be_skipped_or_escaped() -> None:
    sandbox = settings()["sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert "excludedCommands" not in sandbox
    assert set(settings()["permissions"]["deny"]) >= {"WebFetch", "WebSearch"}


def test_network_is_a_strict_allowlist_without_wildcards() -> None:
    network = settings()["sandbox"]["network"]
    assert network["strictAllowlist"] is True
    assert "tlsTerminate" in network  # masking needs it
    assert all("*" not in host for host in network["allowedDomains"])


def test_the_model_key_is_masked_and_reaches_only_the_model_api() -> None:
    sandbox = settings()["sandbox"]
    entries = {e["name"]: e for e in sandbox["credentials"]["envVars"]}
    assert entries["MISTRAL_API_KEY"]["mode"] == "mask"
    assert entries["MISTRAL_API_KEY"]["injectHosts"] == ["api.mistral.ai"]
    assert "api.mistral.ai" in sandbox["network"]["allowedDomains"]
    for name in ("FIELDTEST_APP_PRIVATE_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
        assert entries[name]["mode"] == "deny"


def test_secrets_and_your_own_credentials_are_unreadable() -> None:
    fs = settings()["sandbox"]["filesystem"]
    assert {"~/", "{ROOT}/.env", "{ROOT}/.env.*", "{ROOT}/.private"} <= set(fs["denyRead"])
    # Allowed back: the repo and the tools it runs, never a credentials folder.
    assert "{ROOT}" in fs["allowRead"]
    for allowed in fs["allowRead"]:
        assert not any(c in allowed for c in ("/.config/gh", ".ssh", "Keychains", ".aws"))


def test_every_tracked_file_is_readable_inside_the_sandbox() -> None:
    """`make check` reads every tracked file, so one under a read denial fails it (EPERM)."""
    fs = settings()["sandbox"]["filesystem"]
    repo_denials = [d for d in fs["denyRead"] if d.startswith("{ROOT}/")]
    listed = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for rel in listed:
        path = "{ROOT}/" + rel
        denied = any(fnmatch(path, d) or path.startswith(d + "/") for d in repo_denials)
        assert not denied or path in fs["allowRead"], rel


def test_rendering_denies_writes_to_everything_that_runs_outside_the_sandbox(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / ".claude" / "hooks").mkdir(parents=True)
    rendered = render(TEMPLATE.read_text(encoding="utf-8"), root)
    text = json.dumps(rendered)
    assert "{ROOT}" not in text
    deny_write = rendered["sandbox"]["filesystem"]["denyWrite"]
    for rel in (*GUARDRAIL_PATHS, ".venv", ".git/hooks", ".git/config"):
        assert str(root / rel.rstrip("/")) in deny_write, rel
    assert {"~/.cache/uv", "~/.cache/pre-commit"} <= set(deny_write)
    edits = rendered["permissions"]["deny"]
    assert f"Edit(/{root}/.claude/**)" in edits
    assert f"Edit(/{root}/scripts/guard.py)" in edits
    assert f"Edit(/{root}/.venv/**)" in edits or f"Edit(/{root}/.venv)" in edits
    assert {"WebFetch", "WebSearch"} <= set(edits)
    assert "allowWrite" not in rendered["sandbox"]["filesystem"]


def test_the_driver_renders_the_sandbox_each_session_and_always_passes_it() -> None:
    driver = (ROOT / "scripts" / "autopilot.sh").read_text(encoding="utf-8")
    assert 'scripts/render_sandbox.py "$root" >"$sandbox"' in driver
    assert '--settings "$sandbox"' in driver
    assert 'UV_CACHE_DIR="$root/.autopilot/uv-cache"' in driver
    assert "uv sync --frozen" in driver
    assert "--bare" not in driver.replace("Never add --bare", "")


def test_gh_can_read_its_own_config_inside_the_sandbox() -> None:
    """A Read deny rule is merged into the sandbox: one on `.autopilot/gh` locks gh out of the
    loop's token (the first trial run failed exactly so). The hooks guard it instead."""
    project = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not [r for r in project["permissions"]["deny"] if ".autopilot" in r]
    assert not [p for p in settings()["sandbox"]["filesystem"]["denyRead"] if ".autopilot" in p]
    assert not [r for r in project["permissions"]["deny"] if r.startswith("Write(")]


def test_pytest_skips_every_repo_path_the_sandbox_hides() -> None:
    # pytest stats each entry of the repo root on its way to `testpaths`; a denied entry
    # stops collection with EPERM inside the sandbox unless it is ignored.
    hidden = {
        entry.removeprefix("{ROOT}/")
        for entry in settings()["sandbox"]["filesystem"]["denyRead"]
        if entry.startswith("{ROOT}/")
    }
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert hidden
    expected = {f"--ignore-glob={p}" if "*" in p else f"--ignore={p}" for p in hidden}
    assert expected <= set(addopts)
