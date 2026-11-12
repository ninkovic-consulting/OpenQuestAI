"""Shared fixtures. Every test runs with a temp `VISION_HOME`, a temp `.env`
path and no Keychain, so nothing touches the real home or the repo's `.env`."""

from __future__ import annotations

import asyncio
import contextlib
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
    FakeToolHost,
    FakeVoice,
)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("VISION_HOME", str(home))
    monkeypatch.setenv("VISION_ENV_FILE", str(tmp_path / "missing.env"))
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
