"""The loop's sandbox keeps its safety properties: no way out, no key in sight, no reads of
secrets, and the driver always passes it (ADR 0005)."""

from __future__ import annotations

import json
from typing import Any

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
    deny = settings()["sandbox"]["filesystem"]["denyRead"]
    for path in ("{ROOT}/.env", "{ROOT}/.private", "~/.config/gh", "~/.ssh", "~/Library/Keychains"):
        assert path in deny


def test_the_driver_renders_absolute_paths_and_always_passes_the_settings() -> None:
    rendered = TEMPLATE.read_text(encoding="utf-8").replace("{ROOT}", "/abs/repo")
    deny = json.loads(rendered)["sandbox"]["filesystem"]["denyRead"]
    assert "/abs/repo/.env" in deny
    driver = (ROOT / "scripts" / "autopilot.sh").read_text(encoding="utf-8")
    assert 'sed "s#{ROOT}#$root#g" .claude/sandbox.autopilot.json' in driver
    assert '--settings "$sandbox"' in driver
    assert "--bare" not in driver.replace("Never add --bare", "")


def test_gh_can_read_its_own_config_inside_the_sandbox() -> None:
    """A Read deny rule is merged into the sandbox: one on `.autopilot/gh` locks gh out of the
    loop's token (the first trial run failed exactly so). The hooks guard it instead."""
    project = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not [r for r in project["permissions"]["deny"] if ".autopilot" in r]
    assert not [p for p in settings()["sandbox"]["filesystem"]["denyRead"] if ".autopilot" in p]
    assert not [r for r in project["permissions"]["deny"] if r.startswith("Write(")]
