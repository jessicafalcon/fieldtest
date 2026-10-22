"""Preflight reports which prerequisites are missing, by phase, and never prints a key."""

from __future__ import annotations

from pathlib import Path

import preflight
import pytest
from preflight import PHASES, Result, check_env, current_phase, main

SECRET_VALUE = "mistral-" + "Kq7" * 8


def test_env_check_reports_set_or_not_without_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(f"MISTRAL_API_KEY={SECRET_VALUE}\nFIELDTEST_APP_ID=\n")
    env.chmod(0o644)
    results = {r.name: r for r in check_env(env)}
    assert results["MISTRAL_API_KEY"].ok
    assert results["MISTRAL_API_KEY"].detail == "set"
    assert results["FIELDTEST_APP_ID"].ok is False
    assert results[".env readable only by you"].ok is None  # a warning, not a failure
    assert all(SECRET_VALUE not in r.detail + r.fix for r in results.values())


def test_the_phase_comes_from_progress() -> None:
    assert current_phase("- **Current phase:** 0B — Decisions") == "0B"
    assert current_phase("nothing here") == "0A"
    assert PHASES.index("3b") < PHASES.index("4")


def test_only_checks_needed_by_the_current_phase_fail_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    later = Result("ollama", "3b", False, "not found", "install it")
    now = Result("uv", "0A", True, "0.12.5", "")
    for name in ("check_tools", "check_git", "check_identity"):
        monkeypatch.setattr(preflight, name, lambda: [now])
    monkeypatch.setattr(preflight, "check_env", lambda path: [])
    monkeypatch.setattr(preflight, "check_later_phases", lambda: [later])
    monkeypatch.setattr(preflight, "current_phase", lambda text: "1")
    assert main([]) == 0
    assert "ollama" not in capsys.readouterr().out
    assert main(["--all"]) == 1
    assert "FAIL  ollama (from 3b)" in capsys.readouterr().out
