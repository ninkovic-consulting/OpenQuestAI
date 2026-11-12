"""Background downloads (progress measured in a fake Hugging Face cache) and the doctor."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from settings_fakes import FakeOutside, client, use

from vision.app import Daemon
from vision.settings.downloads import ESTIMATE_BYTES

LOCAL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    return cache


def blob(hub: Path, repo: str, name: str, size: int) -> None:
    blobs = hub / f"models--{repo.replace('/', '--')}" / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    (blobs / name).write_bytes(b"\0" * size)


async def until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def test_idle_downloads(daemon: Daemon, hub: Path) -> None:
    use(daemon)
    async with client(daemon) as http:
        got = (await http.get("/api/downloads")).json()
    assert got["local_model"] == {
        "state": "idle",
        "done_bytes": 0,
        "total_bytes": ESTIMATE_BYTES["local_model"],
        "message": None,
    }
    assert got["speech_models"]["state"] == "idle"


async def test_download_runs_in_the_background(daemon: Daemon, hub: Path) -> None:
    fake = use(daemon, FakeOutside(hold=threading.Event()))
    blob(hub, LOCAL, "abc", 1000)
    blob(hub, LOCAL, "def.incomplete", 500)
    async with client(daemon) as http:
        started = (await http.post("/api/downloads", json={"what": "local_model"})).json()
        assert started["local_model"]["state"] == "running"
        await until(lambda: "download " + LOCAL in fake.calls)
        running = (await http.get("/api/downloads")).json()["local_model"]
        assert running == {
            "state": "running",
            "done_bytes": 1500,
            "total_bytes": 3_000_000,
            "message": None,
        }
        again = (await http.post("/api/downloads", json={"what": "local_model"})).json()
        assert again["local_model"]["state"] == "running"
        assert fake.hold is not None
        fake.hold.set()
        await until(lambda: fake.cache.get(LOCAL) == 1)
        await asyncio.sleep(0.1)
        done = (await http.get("/api/downloads")).json()["local_model"]
    assert done["state"] == "done"
    assert fake.calls.count("download " + LOCAL) == 1


async def test_failed_download_says_why(daemon: Daemon, hub: Path) -> None:
    use(daemon, FakeOutside(download_error=OSError("No space left"), size=None))
    async with client(daemon) as http:
        await http.post("/api/downloads", json={"what": "speech_models"})
        await asyncio.sleep(0.2)
        got = (await http.get("/api/downloads")).json()["speech_models"]
        bad = await http.post("/api/downloads", json={"what": "everything"})
    assert got["state"] == "failed"
    assert "No space left" in got["message"] and "try again" in got["message"]
    assert got["total_bytes"] == ESTIMATE_BYTES["speech_models"]
    assert bad.status_code == 400


async def test_doctor_lists_checks_and_fixable(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.system.built = False
    async with client(daemon) as http:
        got = (await http.get("/api/doctor")).json()
    ids = [c["id"] for c in got["checks"]]
    assert ids[0] == "api_key" and "house" in ids
    assert set(got["checks"][0]) == {"id", "title", "needed_for", "needed", "status", "detail", "fix"}
    assert got["fixable"] == ["local_model", "speech_models", "window"]
    assert isinstance(got["ok"], bool)


async def test_doctor_fixes(daemon: Daemon, hub: Path) -> None:
    fake = use(daemon)
    async with client(daemon) as http:
        window = (await http.post("/api/doctor/fix", json={"id": "window"})).json()
        local = (await http.post("/api/doctor/fix", json={"id": "local_model"})).json()
        github = await http.post("/api/doctor/fix", json={"id": "github"})
        await until(lambda: "build_window" in fake.calls and fake.cache.get(LOCAL) == 1)
    assert window["started"] and "window" in window["message"].lower()
    assert local["started"] and "local model" in local["message"]
    assert github.status_code == 400 and "cannot be fixed" in github.json()["detail"]
