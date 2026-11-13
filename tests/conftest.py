"""Shared fixtures. Every test runs with a temp `VISION_HOME`, a temp `.env`
path, a temp Hugging Face cache and a Keychain that lives in memory, so nothing
touches the real home, a real model, the repo's `.env` or the owner's Keychain.
`launchctl` is never called and the LaunchAgent's plist path is in tmp_path.

The Keychain stand-in is installed when this file is imported and replaced by
an empty one for each test: reading, storing and deleting all stay in memory.
Programs a test starts get no Keychain at all (`PYTHON_KEYRING_BACKEND`).

No test opens the microphone or loads speech models unless it asks to: the
daemon's voice factory gives a silent `FakeVoice` unless `VISION_TEST_VOICE=1`.
Without the `voice` extra, the voice tests are not collected at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import os
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import keyring
import keyring.backend
import pytest
import uvicorn
from keyring.errors import PasswordDeleteError

from vision.app import Components, Daemon
from vision.core import launchd
from vision.core.bus import Bus
from vision.core.config import Config, load_config
from vision.testing.fakes import (
    FakeBrain,
    FakeBudget,
    FakeHouse,
    FakeMemory,
    FakePresenceReader,
    FakeToolHost,
    FakeVoice,
)

if importlib.util.find_spec("mlx_audio") is None:
    collect_ignore_glob = ["test_voice_*.py"]


class MemoryKeyring(keyring.backend.KeyringBackend):
    """The Keychain for tests: a dictionary. It behaves as the macOS one does for a missing entry."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.entries:
            raise PasswordDeleteError("Password not found")
        del self.entries[(service, username)]


NO_KEYCHAIN = "keyring.backends.null.Keyring"
"""For programs a test starts: they read nothing and store nothing."""

# Before any test or fixture runs, so nothing that is collected can reach the real one.
keyring.set_keyring(MemoryKeyring())
os.environ["PYTHON_KEYRING_BACKEND"] = NO_KEYCHAIN


@pytest.fixture(autouse=True)
def memory_keychain(monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryKeyring]:
    """An empty Keychain in memory for each test; the owner's is never read, written or deleted from."""
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", NO_KEYCHAIN)
    yield memory
    keyring.set_keyring(MemoryKeyring())


@pytest.fixture(autouse=True)
def stand_in_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daemon gets a silent voice unless real voice is asked for."""
    if os.environ.get("VISION_TEST_VOICE") != "1":
        monkeypatch.setattr("vision.voice.make_voice", lambda config, bus: FakeVoice())


@pytest.fixture(autouse=True)
def stand_in_presence(monkeypatch: pytest.MonkeyPatch) -> FakePresenceReader:
    """The daemon reads a fake idle time: the owner at the Mac, until a test says otherwise."""
    reader = FakePresenceReader()
    monkeypatch.setattr("vision.presence.default_reader", lambda: reader)
    return reader


@pytest.fixture(autouse=True)
def no_launchctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No test reaches `launchctl` or the real `~/Library/LaunchAgents`; the agent's plist lives in tmp_path."""

    def refuse(args: list[str], *, check: bool) -> None:
        raise AssertionError(f"a test called launchctl {' '.join(args)}")

    plist = tmp_path / "LaunchAgents" / f"{launchd.LABEL}.plist"
    monkeypatch.setattr(launchd, "_launchctl", refuse)
    monkeypatch.setattr(launchd, "plist_path", lambda: plist)
    return plist


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("VISION_HOME", str(home))
    monkeypatch.setenv("VISION_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf-hub"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield home


@pytest.fixture
def config(isolated_env: Path) -> Config:
    return load_config()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.asynccontextmanager
async def served(d: Daemon) -> AsyncIterator[Daemon]:
    """Run the daemon's app under uvicorn on its port until the block ends."""
    server = uvicorn.Server(
        uvicorn.Config(d.app, host="127.0.0.1", port=d.port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started, "server did not start"
    try:
        yield d
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


def all_fakes(bus: Bus) -> Components:
    return Components(
        brain=FakeBrain(),
        tools=FakeToolHost(),
        memory=FakeMemory(),
        budget=FakeBudget(),
        voice=FakeVoice(),
        house=FakeHouse(),
    )


@pytest.fixture
async def daemon(config: Config) -> AsyncIterator[Daemon]:
    """A daemon with the real parts on the fake brain, on a free local port."""
    async with served(Daemon(config, fake_brain=True, port=free_port())) as d:
        yield d


@pytest.fixture
async def fake_daemon(config: Config) -> AsyncIterator[Daemon]:
    """A daemon whose every part is a fake from `vision.testing.fakes`."""
    async with served(Daemon(config, port=free_port(), components=all_fakes)) as d:
        yield d
