"""The phone bot's token, in the macOS Keychain beside the API key. Never logged.

Same mechanism as `vision.core.secrets`: `keyring`, service `vision`, its own
account. The token is written once from the settings window, read only by the
daemon to talk to the service, and never returned by a route, written to a
file or put in a backup.
"""

from __future__ import annotations

import logging
from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from vision.core.secrets import KEYRING_SERVICE

KEYRING_ACCOUNT = "phone_bot_token"

log = logging.getLogger(__name__)


class TokenStore(Protocol):
    def get(self) -> str | None: ...
    def put(self, token: str) -> None:
        """Raises `KeyringError` or `OSError` when it cannot be stored."""
        ...

    def delete(self) -> None: ...


class KeychainToken:
    def get(self) -> str | None:
        try:
            return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) or None
        except KeyringError as exc:
            log.info("keychain unavailable for the phone token: %s", type(exc).__name__)
            return None

    def put(self, token: str) -> None:
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token)

    def delete(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except PasswordDeleteError:
            return
