"""CODEOWNERS gives the owner exactly the guardrail paths, so GitHub enforces their review."""

from __future__ import annotations

from guard_rules import GUARDRAIL_PATHS

from tests.conftest import ROOT


def test_codeowners_covers_every_guardrail_path() -> None:
    lines = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
    owned = {line.split()[0].lstrip("/") for line in lines if line and not line.startswith("#")}
    assert owned == set(GUARDRAIL_PATHS)
    assert ".github/CODEOWNERS" in owned
