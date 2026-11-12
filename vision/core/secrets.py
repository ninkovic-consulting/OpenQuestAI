"""The Anthropic API key, looked up in a fixed order. The value is never logged.

Order:
1. The macOS Keychain (service `vision`, account `anthropic_api_key`), via `keyring`.
2. `ANTHROPIC_API_KEY` in a `.env` file: `$VISION_ENV_FILE`, or `.env` at the repo root.
3. `ANTHROPIC_API_KEY` in the process environment.

`vision auth` stores a key in the Keychain with `store_api_key`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import keyring
from keyring.errors import KeyringError

log = logging.getLogger(__name__)

KEYRING_SERVICE = "vision"
KEYRING_ACCOUNT = "anthropic_api_key"
ENV_NAME = "ANTHROPIC_API_KEY"
REPO_ROOT = Path(__file__).resolve().parents[2]


def env_file_path() -> Path:
    override = os.environ.get("VISION_ENV_FILE")
    return Path(override).expanduser() if override else REPO_ROOT / ".env"


def _from_keychain() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) or None
    except KeyringError as exc:
        log.info("keychain unavailable: %s", type(exc).__name__)
        return None


def _from_env_file(path: Path) -> str | None:
    """Read one key from a dotenv file: `KEY=value`, optional `export` and quotes."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        name, sep, value = line.partition("=")
        if not sep or name.strip() != ENV_NAME:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        return value or None
    return None


def get_api_key() -> str | None:
    """The Anthropic API key, or None when none is stored anywhere."""
    return (
        _from_keychain()
        or _from_env_file(env_file_path())
        or (os.environ.get(ENV_NAME) or None)
    )


def api_key_source() -> str | None:
    """Where the key would come from: `keychain`, `env_file`, `environment`, or None."""
    if _from_keychain():
        return "keychain"
    if _from_env_file(env_file_path()):
        return "env_file"
    if os.environ.get(ENV_NAME):
        return "environment"
    return None


def store_api_key(key: str) -> None:
    """Save the key in the Keychain."""
    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
