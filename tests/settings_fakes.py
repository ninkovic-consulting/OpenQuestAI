"""A fake outside world for the settings routes, and a client for a served daemon."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import httpx
from test_setup import FakeSystem

from vision.app import Daemon
from vision.core.config import Config
from vision.settings import SettingsService
from vision.settings.outside import AudioDevice, KeyRefused, ModelRow, Unreachable
from vision.setup.system import System
from vision.voice.errors import VoiceUnavailable, mic_permission_hint

GOOD_KEY = "sk-ant-api03-" + "Q" * 40


@dataclass
class FakeOutside:
    key: str | None = None
    models: list[ModelRow] = field(
        default_factory=lambda: [
            ModelRow("claude-opus-5-5", "Claude Opus 5.5", 1_000_000, 128_000, None),
            ModelRow("claude-brand-new", "Claude Brand New", 200_000, 64_000, None),
        ]
    )
    api: str = "accepted"
    """`accepted`, `refused` or `unreachable`: how the Models API answers."""
    installed: bool = True
    devices: list[AudioDevice] = field(
        default_factory=lambda: [
            AudioDevice("MacBook Pro Microphone", 1, 0, True, False),
            AudioDevice("MacBook Pro Speakers", 0, 2, False, True),
        ]
    )
    cache: dict[str, int] = field(default_factory=dict)
    heard: str = "testing one two"
    mic_error: Exception | None = None
    size: int | None = 3_000_000
    download_error: Exception | None = None
    hold: threading.Event | None = None
    """When set, downloads wait for it, so a test can see them running."""
    window_ok: bool = True
    system: FakeSystem = field(default_factory=FakeSystem)
    calls: list[str] = field(default_factory=list)

    def api_key(self) -> str | None:
        return self.key

    def key_source(self) -> str | None:
        return "keychain" if self.key else None

    def store_key(self, key: str) -> None:
        self.calls.append("store_key")
        self.key = key

    def delete_key(self) -> None:
        self.calls.append("delete_key")
        self.key = None

    def list_models(self, key: str) -> list[ModelRow]:
        self.calls.append("list_models")
        if self.api == "refused":
            raise KeyRefused
        if self.api == "unreachable":
            raise Unreachable
        return list(self.models)

    def voice_installed(self) -> bool:
        return self.installed

    def audio_devices(self) -> list[AudioDevice]:
        self.calls.append("audio_devices")
        return list(self.devices)

    async def mic_test(self, config: Config, seconds: float) -> str:
        self.calls.append("mic_test")
        if self.mic_error is not None:
            raise self.mic_error
        return self.heard

    def cached_size(self, repo: str, needs: str = "*") -> int | None:
        return self.cache.get(repo)

    def download_size(self, repos: list[str]) -> int | None:
        return self.size

    def download(self, repos: list[str]) -> None:
        self._download(repos)

    def download_local_model(self, config: Config) -> None:
        self._download([config.brain.local_model])

    def _download(self, repos: list[str]) -> None:
        self.calls.append(f"download {' '.join(repos)}")
        if self.hold is not None:
            self.hold.wait(5)
        if self.download_error is not None:
            raise self.download_error
        for repo in repos:
            self.cache[repo] = 1

    def build_window(self) -> bool:
        self.calls.append("build_window")
        return self.window_ok

    def doctor_system(self) -> System:
        return self.system


def denied() -> VoiceUnavailable:
    return VoiceUnavailable(f"The microphone sends only silence. {mic_permission_hint()}")


def service(d: Daemon) -> SettingsService:
    settings: SettingsService = d.app.state.settings
    return settings


def use(d: Daemon, outside: FakeOutside | None = None) -> FakeOutside:
    """Give the daemon's settings a fake outside world and return it."""
    fake = outside or FakeOutside()
    service(d).outside = fake
    return fake


def client(d: Daemon, *, token: bool = True) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {d.token}"} if token else {}
    return httpx.AsyncClient(base_url=f"http://127.0.0.1:{d.port}", headers=headers, timeout=10)
