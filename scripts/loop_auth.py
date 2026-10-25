#!/usr/bin/env python3
"""The loop's own GitHub identity: short-lived tokens for the fieldtest GitHub App.

The App's ID, installation ID and private key live in `.env`, the one place a key lives.
This script mints a one-hour installation token from them and never prints it or the key.

  write-gh-config DIR   write DIR/hosts.yml so `GH_CONFIG_DIR=DIR gh …` and git (through
                        `gh auth git-credential`) act as the App. Atomic, mode 0600.
                        `scripts/autopilot.sh` refreshes it every 30 minutes and deletes it on exit.
  identity              print the App's bot login and noreply email as JSON, the content of
                        `.github/loop-identity.json`
  check                 confirm the keys are set and a token can be minted

Claude sessions never run it (bash_policy.py); the driver does.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"
APP_KEYS = ("FIELDTEST_APP_ID", "FIELDTEST_APP_INSTALLATION_ID", "FIELDTEST_APP_PRIVATE_KEY")

Opener = Callable[..., Any]


class AuthError(Exception):
    """A configuration or GitHub error, worded so it never contains a secret."""


def read_env(path: Path) -> dict[str, str]:
    """`KEY=VALUE` lines of a dotenv file; quotes stripped, comments and blanks skipped.

    >>> import tempfile, pathlib
    >>> p = pathlib.Path(tempfile.mkdtemp()) / "e"
    >>> _ = p.write_text("# c\\nexport A='1'\\nB=\\nC = \\"x y\\"\\n")
    >>> read_env(p)
    {'A': '1', 'B': '', 'C': 'x y'}
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def app_settings(env: dict[str, str]) -> tuple[str, str, str]:
    """(app ID, installation ID, PEM private key), or an error naming what's missing."""
    missing = [key for key in APP_KEYS if not env.get(key)]
    if missing:
        raise AuthError(
            f"not set in .env: {', '.join(missing)} (PROJECT-BRIEF.md §12, the loop's GitHub App)"
        )
    try:
        pem = base64.b64decode(env["FIELDTEST_APP_PRIVATE_KEY"], validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise AuthError(
            "FIELDTEST_APP_PRIVATE_KEY is not the base64 of the App's .pem file"
        ) from error
    if "PRIVATE KEY-----" not in pem:
        raise AuthError("FIELDTEST_APP_PRIVATE_KEY does not decode to a PEM private key")
    return env["FIELDTEST_APP_ID"], env["FIELDTEST_APP_INSTALLATION_ID"], pem


def app_jwt(app_id: str, pem: str, now: int) -> str:
    """The App's own JWT: RS256, issued a minute in the past for clock skew, 9 minutes long."""
    import jwt  # dev dependency; imported here so `read_env` works without it

    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, pem, algorithm="RS256")


def call(method: str, path: str, credential: str, opener: Opener) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 (fixed https API origin)
        f"{API}{path}",
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {credential}",
            "User-Agent": "fieldtest-loop",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise AuthError(f"GitHub answered {error.code} to {method} {path}") from None
    except urllib.error.URLError as error:
        raise AuthError(f"GitHub unreachable for {method} {path}: {error.reason}") from None
    if not isinstance(data, dict):
        raise AuthError(f"unexpected response to {method} {path}")
    return data


def installation_token(env: dict[str, str], now: int, opener: Opener) -> str:
    app_id, installation_id, pem = app_settings(env)
    data = call(
        "POST",
        f"/app/installations/{installation_id}/access_tokens",
        app_jwt(app_id, pem, now),
        opener,
    )
    return str(data["token"])


def hosts_yml(credential: str, login: str) -> str:
    """gh's host config for one account whose credential is stored in the file, not a keyring."""
    return (
        "github.com:\n"
        f"    users:\n        {login}:\n            oauth_token: {credential}\n"
        "    git_protocol: https\n"
        f"    oauth_token: {credential}\n"
        f"    user: {login}\n"
    )


def write_private(path: Path, text: str) -> None:
    """Write atomically with mode 0600, so no reader ever sees a partial or open file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def loop_login(root: Path) -> str:
    identity = json.loads((root / ".github" / "loop-identity.json").read_text(encoding="utf-8"))
    login = identity.get("bot_login") or ""
    if not login:
        raise AuthError(".github/loop-identity.json has no bot_login yet (PROJECT-BRIEF.md §12)")
    return str(login)


def write_gh_config(
    directory: Path, env: dict[str, str], login: str, now: int, opener: Opener
) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    minted = installation_token(env, now, opener)
    write_private(directory / "config.yml", "git_protocol: https\nprompt: disabled\n")
    write_private(directory / "hosts.yml", hosts_yml(minted, login))


def identity(env: dict[str, str], now: int, opener: Opener) -> dict[str, str]:
    app_id, _, pem = app_settings(env)
    slug = call("GET", "/app", app_jwt(app_id, pem, now), opener)["slug"]
    login = f"{slug}[bot]"
    minted = installation_token(env, now, opener)
    user = call("GET", f"/users/{urllib.parse.quote(login)}", minted, opener)
    return {
        "app_slug": slug,
        "bot_login": login,
        "bot_email": f"{user['id']}+{login}@users.noreply.github.com",
    }


def main(argv: list[str], *, root: Path = ROOT, opener: Opener = urllib.request.urlopen) -> int:
    env = read_env(root / ".env")
    now = int(time.time())
    command, *rest = argv or [""]
    if command == "write-gh-config" and rest:
        write_gh_config(Path(rest[0]), env, loop_login(root), now, opener)
    elif command == "identity":
        print(json.dumps(identity(env, now, opener), indent=2, sort_keys=True))
    elif command == "check":
        installation_token(env, now, opener)
        print("loop identity: the App's keys are set and GitHub issues it a token")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except AuthError as error:
        print(f"loop-auth: {error}", file=sys.stderr)
        sys.exit(1)
