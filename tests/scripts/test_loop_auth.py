"""The loop's App identity: tokens are minted from .env and never printed or logged."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import stat
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from loop_auth import AuthError, app_jwt, app_settings, main

FAKE_INSTALLATION_TOKEN = "ghs_" + "T0k" * 12


@pytest.fixture(scope="module")
def pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def root(tmp_path: Path, pem: str) -> Path:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "loop-identity.json").write_text(
        json.dumps({"bot_login": "fieldtest-loop[bot]"})
    )
    encoded = base64.b64encode(pem.encode()).decode()
    (tmp_path / ".env").write_text(
        f"FIELDTEST_APP_ID=123\nFIELDTEST_APP_INSTALLATION_ID=456\n"
        f"FIELDTEST_APP_PRIVATE_KEY={encoded}\nMISTRAL_API_KEY=unused\n"
    )
    return tmp_path


class FakeGitHub:
    """An in-process stand-in for the three API calls; records what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, request: Any, timeout: float) -> Any:
        self.calls.append(
            (request.get_method(), request.full_url, request.headers["Authorization"])
        )
        url = request.full_url
        if url.endswith("/access_tokens"):
            body: dict[str, Any] = {"token": FAKE_INSTALLATION_TOKEN}
        elif url.endswith("/app"):
            body = {"slug": "fieldtest-loop"}
        else:
            body = {"id": 987}
        return contextlib.nullcontext(io.BytesIO(json.dumps(body).encode()))


def test_the_app_jwt_is_rs256_short_lived_and_issued_by_the_app(pem: str) -> None:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private = load_pem_private_key(pem.encode(), password=None)
    assert isinstance(private, rsa.RSAPrivateKey)
    public = private.public_key()
    claims = jwt.decode(
        app_jwt("123", pem, now=1_000_000),
        public,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {"iat": 999_940, "exp": 1_000_540, "iss": "123"}


def test_missing_keys_are_named_and_no_value_is_echoed() -> None:
    with pytest.raises(AuthError) as error:
        app_settings({"FIELDTEST_APP_ID": "123", "MISTRAL_API_KEY": "secret-value"})
    message = str(error.value)
    assert "FIELDTEST_APP_INSTALLATION_ID" in message
    assert "FIELDTEST_APP_PRIVATE_KEY" in message
    assert "secret-value" not in message
    assert "123" not in message


def test_a_key_that_is_not_base64_pem_is_refused() -> None:
    env = {
        "FIELDTEST_APP_ID": "1",
        "FIELDTEST_APP_INSTALLATION_ID": "2",
        "FIELDTEST_APP_PRIVATE_KEY": base64.b64encode(b"not a key").decode(),
    }
    with pytest.raises(AuthError, match="PEM"):
        app_settings(env)


def test_write_gh_config_stores_the_token_privately_and_prints_nothing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    target = root / ".autopilot" / "gh"
    assert main(["write-gh-config", str(target)], root=root, opener=github) == 0
    hosts = target / "hosts.yml"
    assert stat.S_IMODE(hosts.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    text = hosts.read_text()
    assert f"oauth_token: {FAKE_INSTALLATION_TOKEN}" in text
    assert "user: fieldtest-loop[bot]" in text
    out = capsys.readouterr()
    assert FAKE_INSTALLATION_TOKEN not in out.out + out.err
    method, url, auth = github.calls[0]
    assert (method, url) == ("POST", "https://api.github.com/app/installations/456/access_tokens")
    assert auth.startswith("Bearer ey")  # the App's JWT, not a stored token


def test_identity_derives_the_bot_login_and_noreply_email(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["identity"], root=root, opener=FakeGitHub()) == 0
    assert json.loads(capsys.readouterr().out) == {
        "app_slug": "fieldtest-loop",
        "bot_email": "987+fieldtest-loop[bot]@users.noreply.github.com",
        "bot_login": "fieldtest-loop[bot]",
    }


def test_no_identity_configured_is_a_clear_error(root: Path) -> None:
    (root / ".github" / "loop-identity.json").write_text(json.dumps({"bot_login": ""}))
    with pytest.raises(AuthError, match="bot_login"):
        main(["write-gh-config", str(root / "gh")], root=root, opener=FakeGitHub())
