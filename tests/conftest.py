"""Shared fixtures. Every test runs with a temp `VISION_HOME`, a temp `.env`
path, a temp Hugging Face cache and no Keychain, so nothing touches the real
home, a real model or the repo's `.env`.

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

import pytest
import uvicorn

from vision.app import Components, Daemon
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
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("VISION_HOME", str(home))
    monkeypatch.setenv("VISION_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf-hub"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("keyring.get_password", lambda service, account: None)
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
