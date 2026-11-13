"""No test can reach the owner's Keychain: reading, storing and deleting stay in memory.

A test once removed the real bot token each time the suite ran, because only
reading was replaced. These tests fail if the stand-in is ever taken away.
"""

from __future__ import annotations

import subprocess
import sys

import keyring
from conftest import NO_KEYCHAIN, MemoryKeyring

from vision.core import secrets
from vision.core.secrets import KEYRING_SERVICE
from vision.remote.token import KEYRING_ACCOUNT, KeychainToken


def test_the_keychain_in_a_test_is_the_one_in_memory(memory_keychain: MemoryKeyring) -> None:
    assert keyring.get_keyring() is memory_keychain
    assert memory_keychain.entries == {}


def test_the_bot_token_is_stored_read_and_removed_in_memory(memory_keychain: MemoryKeyring) -> None:
    tokens = KeychainToken()
    tokens.put("a-bot-token-for-tests")
    assert memory_keychain.entries == {(KEYRING_SERVICE, KEYRING_ACCOUNT): "a-bot-token-for-tests"}
    assert tokens.get() == "a-bot-token-for-tests"
    tokens.delete()
    tokens.delete()  # a missing entry is not an error, as on the Mac
    assert memory_keychain.entries == {} and tokens.get() is None


def test_the_api_key_is_stored_in_memory(memory_keychain: MemoryKeyring) -> None:
    secrets.store_api_key("an-api-key-for-tests")
    assert list(memory_keychain.entries.values()) == ["an-api-key-for-tests"]


def test_what_one_test_stores_the_next_does_not_see(memory_keychain: MemoryKeyring) -> None:
    assert memory_keychain.entries == {}  # the tests above stored entries in theirs


def test_a_program_a_test_starts_has_no_keychain() -> None:
    asked = subprocess.run(
        [sys.executable, "-c", "import keyring; k = keyring.get_keyring(); print(type(k).__module__, type(k).__name__)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert asked.stdout.split() == NO_KEYCHAIN.rsplit(".", 1)
