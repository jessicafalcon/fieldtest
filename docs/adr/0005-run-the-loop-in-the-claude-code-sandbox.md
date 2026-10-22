# 0005. Run the loop's commands in the Claude Code sandbox, with the model key masked

Status: Accepted
Date: 2026-10-22

## Context and Problem Statement

The hooks check the *text* of a command, not what the code it runs does. The loop writes
code and then runs it: tests, the extraction runner, and the smoke call. A live call loaded
`.env` through an allowlist of commands (`uv run --env-file .env fieldtest run …`), but
`fieldtest run` executes `src/` as it stands on the branch, written minutes earlier and not
yet reviewed. Any test could also `open(".env")`. Outbound network was unrestricted. The
loop reads untrusted text: public PR comments, tender documents, model outputs. So an
injected instruction could lead it to write code that prints the API key or the App's
private key, or sends it out, and no hook would see it.

## Considered Options

1. **Keep the allowlist and rely on review.** Review happens after the code has already run.
2. **Run live calls only from reviewed code on `main`.** It closes the key path for live
   calls, but not reads from tests, and not the network.
3. **Claude Code's built-in Bash sandbox**, enforced by the OS on every command and every
   process it starts, with credential masking.

## Decision Outcome

Chosen option: **3**, because it limits what code *can* do, not what a command looks like.

- The driver passes `.claude/sandbox.autopilot.json` with `--settings`. Masking, TLS
  termination and the strict allowlist are honoured only from there or from user settings,
  never from a repository's settings. The driver renders `{ROOT}` to the repo's absolute
  path, since relative sandbox paths would resolve against the settings file's location.
- **Reads denied:** `.env`, `.private/`, `~/.config/gh` (the owner's GitHub login), `~/.ssh`,
  `~/.aws`, `~/.gnupg`, `~/.netrc`, Docker credentials, keychains, Claude's own credentials.
- **Network:** a strict allowlist (GitHub, PyPI, the Mistral API and docs, BOAMP open data);
  any other host is denied, never prompted.
- **The model key is masked.** The driver exports `MISTRAL_API_KEY` from `.env`. Sandboxed
  commands see only a per-session placeholder, and the proxy swaps in the real value only
  on requests to `api.mistral.ai`. If substitution doesn't work, authentication fails and
  nothing is exposed. The App's variables and any GitHub token are unset inside the sandbox.
- **No escape:** `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, no
  `excludedCommands`, and the WebFetch and WebSearch tools, which bypass the network
  allowlist, are denied.
- No command loads `.env` any more; `bash_policy.py` blocks `--env-file .env` outright.

### Consequences

- Good, because code the loop writes can call the model but can never see or send the
  key, can't read the owner's GitHub login, and can't reach an unlisted host.
- Good, because a host the work needs is a reviewed change to a guardrail file.
- Bad, because hooks, the file tools and the Claude process itself run outside the
  sandbox. The hooks are guardrails for that reason, and the file tools are covered by
  `protect_files.py` and the permission rules.
- Bad, because masking depends on the sandbox's TLS termination, which is experimental.
  Whether Python's HTTP clients trust its session certificate is **unverified** until the
  first trial run; the fallback is the custom CA option (`caCertPath`, `caKeyPath`).
- Bad, because GitHub stays reachable, and a sandboxed command could still post text there.
  The key it could post is only the placeholder, and the guard checks published text.
