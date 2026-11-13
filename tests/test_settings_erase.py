"""Delete all data: what the app made goes, what it did not make stays, then the daemon stops.

Every deletion happens in this test's own folders: the data folder, the
Hugging Face cache and the Keychain are the temp ones from `conftest.py`, and
the LaunchAgent is a fake (`launchctl` itself is refused for every test).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from conftest import MemoryKeyring, free_port, served
from settings_fakes import client, service

from vision.app import Daemon
from vision.brains import catalog
from vision.core.config import Config, GateConfig
from vision.core.secrets import KEYRING_ACCOUNT as KEY_ACCOUNT
from vision.core.secrets import KEYRING_SERVICE
from vision.house.tools import load_catalog
from vision.remote.token import KEYRING_ACCOUNT as BOT_ACCOUNT
from vision.settings import backups, erase
from vision.setup import hf_cache
from vision.voice.settings import VoiceSettings

CONFIRM = {"confirm": erase.CONFIRM}


@dataclass
class FakeAgent:
    """The LaunchAgent `vision install` writes, without launchd."""

    present: bool = True
    own: bool = False
    calls: list[str] = field(default_factory=list)

    def installed(self) -> bool:
        return self.present

    def runs_this_daemon(self) -> bool:
        return self.own

    def uninstall(self) -> None:
        self.calls.append("uninstall")

    def remove_plist(self) -> None:
        self.calls.append("remove_plist")

    def unload(self) -> None:
        self.calls.append("unload")


@dataclass
class Exits:
    count: int = 0

    def __call__(self) -> None:
        self.count += 1


@pytest.fixture
async def eraser(config: Config, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[Daemon, FakeAgent, Exits]]:
    """A daemon on the fake brain whose exit and LaunchAgent are recorded, not acted on."""
    monkeypatch.setattr(erase, "EXIT_DELAY_S", 0.0)
    d = Daemon(config, fake_brain=True, port=free_port())
    exits = Exits()
    monkeypatch.setattr(d, "request_exit", exits)
    agent = FakeAgent()
    async with served(d):
        service(d).eraser.agent = agent
        yield d, agent, exits


def model(repo: str, size: int) -> None:
    """A downloaded repo in the test's Hugging Face cache: a blob and a snapshot linking to it."""
    folder = hf_cache.hub_cache() / f"models--{repo.replace('/', '--')}"
    (folder / "blobs").mkdir(parents=True)
    (folder / "blobs" / "abc123").write_bytes(b"\0" * size)
    (folder / "snapshots" / "rev1").mkdir(parents=True)
    (folder / "snapshots" / "rev1" / "model.safetensors").symlink_to(folder / "blobs" / "abc123")


def on_disk(repo: str) -> bool:
    return (hf_cache.hub_cache() / f"models--{repo.replace('/', '--')}").exists()


def fill(home: Path, outside: Path) -> None:
    """One of everything the app writes in its data folder, beside what it was already given."""
    for name in ("config.toml", "budget.json", "automations.json", "jobs.json", "phone.json", "proposals.json"):
        (home / name).write_text("{}\n")
    for name in (".house.toml.x1y2.tmp", "jobs.json.broken", "budget.tmp", ".DS_Store"):
        (home / name).write_text("")  # the log's own -wal and -shm are SQLite's, open while it runs
    (home / "made-tools" / "word-count" / "versions").mkdir(parents=True)
    (home / "made-tools" / "word-count" / "versions" / "1.py").write_text("print(1)\n")
    (home / "images").mkdir(exist_ok=True)
    (home / "images" / "a1b2.png").write_bytes(b"png")
    (home / "logs").mkdir(exist_ok=True)
    (home / "logs" / "app-daemon.log").write_text("started\n")
    (home / "backups" / "20261112-130500-settings").mkdir(parents=True)
    (home / "backups" / "20261112-130500-settings" / "config.toml").write_text("")
    (home / "espeak-ng-data").symlink_to(outside / "espeak", target_is_directory=True)
    (home / "house" / "elsewhere").symlink_to(outside / "kept", target_is_directory=True)


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """Folders outside the data folder that links in it point at; they must survive."""
    root = tmp_path / "outside"
    (root / "espeak").mkdir(parents=True)
    (root / "espeak" / "phontab").write_text("espeak data\n")
    (root / "kept").mkdir()
    (root / "kept" / "notes.md").write_text("not the app's\n")
    return root


# --- Refusals: nothing happens ----------------------------------------------------------------


@pytest.mark.parametrize("body", [{}, {"confirm": "yes"}, {"confirm": True}, {"confirm": "DELETE ALL DATA"}])
async def test_refused_without_the_confirmation(
    eraser: tuple[Daemon, FakeAgent, Exits], memory_keychain: MemoryKeyring, body: dict[str, object]
) -> None:
    d, agent, exits = eraser
    memory_keychain.set_password(KEYRING_SERVICE, KEY_ACCOUNT, "sk-ant-for-tests")
    before = sorted(p.name for p in d.config.paths.home.iterdir())
    async with client(d) as http:
        answer = await http.post("/api/delete-all", json=body)
        after = await http.get("/api/settings")
    assert answer.status_code == 400 and "Nothing was deleted" in answer.json()["detail"]
    assert after.status_code == 200  # still running
    assert sorted(p.name for p in d.config.paths.home.iterdir()) == before
    assert memory_keychain.entries and agent.calls == [] and exits.count == 0 and not d.erased


@pytest.mark.parametrize("where", ["home", "inside"])
async def test_refused_when_the_data_folder_is_the_home_folder_or_above_it(
    eraser: tuple[Daemon, FakeAgent, Exits], monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    d, agent, exits = eraser
    home = d.config.paths.home
    user = home if where == "home" else home / "Sam"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user))
    before = sorted(p.name for p in home.iterdir())
    async with client(d) as http:
        answer = await http.post("/api/delete-all", json=CONFIRM)
    assert answer.status_code == 400
    assert "home folder or a folder above it" in answer.json()["detail"]
    assert sorted(p.name for p in home.iterdir()) == before
    assert agent.calls == [] and exits.count == 0 and not d.erased


def test_danger(tmp_path: Path) -> None:
    user = tmp_path / "Users" / "sam"
    user.mkdir(parents=True)
    assert erase.danger(Path("/"), user) is not None
    assert erase.danger(user, user) is not None
    assert erase.danger(tmp_path / "Users", user) is not None
    assert erase.danger(user / "Library" / "Application Support" / "Vision", user) is None
    (tmp_path / "link").symlink_to(tmp_path / "Users", target_is_directory=True)
    assert erase.danger(tmp_path / "link", user) is not None  # followed to where it really is


# --- Doing it -----------------------------------------------------------------------------------


async def test_removes_what_the_app_made_and_leaves_the_rest(
    eraser: tuple[Daemon, FakeAgent, Exits], memory_keychain: MemoryKeyring, outside: Path
) -> None:
    d, agent, exits = eraser
    home = d.config.paths.home
    memory_keychain.set_password(KEYRING_SERVICE, KEY_ACCOUNT, "sk-ant-for-tests")
    memory_keychain.set_password(KEYRING_SERVICE, BOT_ACCOUNT, "a-bot-token-for-tests")
    fill(home, outside)
    (home / "Sam's notes.txt").write_text("mine\n")
    (home / "harbor-books").mkdir()
    (home / "harbor-books" / "plan.md").write_text("mine too\n")
    (home / "a-link").symlink_to(outside / "kept", target_is_directory=True)
    async with client(d) as http:
        answer = (await http.post("/api/delete-all", json=CONFIRM)).json()
        after = await http.get("/api/settings")
    left = {x["name"]: x["why"] for x in answer["left"]}
    assert left == {"Sam's notes.txt": erase.NOT_MADE, "harbor-books": erase.NOT_MADE, "a-link": erase.NOT_MADE}
    assert sorted(p.name for p in home.iterdir()) == ["Sam's notes.txt", "a-link", "harbor-books"]
    assert (home / "harbor-books" / "plan.md").read_text() == "mine too\n"
    for name in ("token", "log.db", "house", "house.toml", "config.toml", "images", "logs", "backups", "made-tools",
                 "espeak-ng-data", "jobs.json.broken", ".house.toml.x1y2.tmp", ".DS_Store"):
        assert name in answer["removed"], name
    assert answer["folder_removed"] is False and "Sam's notes.txt" in answer["message"]
    # Links were removed, never followed.
    assert (outside / "espeak" / "phontab").read_text() == "espeak data\n"
    assert (outside / "kept" / "notes.md").read_text() == "not the app's\n"
    assert memory_keychain.entries == {}
    assert answer["keychain"]["ok"] is True
    assert answer["models"] is None
    assert after.status_code == 503 and d.erased
    for _ in range(100):
        if exits.count:
            break
        await asyncio.sleep(0.01)
    assert exits.count == 1


async def test_the_folder_goes_when_only_the_apps_files_were_in_it(
    config: Config, monkeypatch: pytest.MonkeyPatch, outside: Path, memory_keychain: MemoryKeyring
) -> None:
    """Through the daemon's own shutdown too: nothing writes the folder again."""
    monkeypatch.setattr(erase, "EXIT_DELAY_S", 0.0)
    d = Daemon(config, fake_brain=True, port=free_port())
    exits = Exits()
    monkeypatch.setattr(d, "request_exit", exits)
    home = config.paths.home
    async with served(d):
        service(d).eraser.agent = FakeAgent(present=False)
        d.components.budget.record("claude-opus-5-5", 1_000, 0)
        fill(home, outside)
        async with client(d) as http:
            answer = (await http.post("/api/delete-all", json=CONFIRM)).json()
        assert answer["left"] == [] and answer["folder_removed"] is True
        assert answer["launch_agent"] == {"installed": False, "removed": False, "message": ""}
        assert not home.exists()
    assert not home.exists()  # the server's shutdown wrote nothing back
    assert "The data folder is gone." in answer["message"]


async def test_the_launch_agent_is_removed(eraser: tuple[Daemon, FakeAgent, Exits]) -> None:
    d, agent, exits = eraser
    async with client(d) as http:
        answer = (await http.post("/api/delete-all", json=CONFIRM)).json()
    assert agent.calls == ["uninstall"] and answer["launch_agent"]["removed"] is True


async def test_an_agent_that_runs_this_daemon_is_unloaded_after_the_answer(
    eraser: tuple[Daemon, FakeAgent, Exits],
) -> None:
    d, agent, exits = eraser
    agent.own = True
    async with client(d) as http:
        answer = (await http.post("/api/delete-all", json=CONFIRM)).json()
    assert answer["launch_agent"]["removed"] is True
    for _ in range(100):
        if exits.count:
            break
        await asyncio.sleep(0.01)
    assert agent.calls == ["remove_plist", "unload"] and exits.count == 1


async def test_a_keychain_failure_is_reported_and_the_rest_goes_on(
    eraser: tuple[Daemon, FakeAgent, Exits], monkeypatch: pytest.MonkeyPatch
) -> None:
    d, _, _ = eraser

    def broken() -> None:
        raise OSError("the Keychain is locked")

    monkeypatch.setattr(service(d).outside, "delete_key", broken)
    async with client(d) as http:
        answer = (await http.post("/api/delete-all", json=CONFIRM)).json()
    assert answer["keychain"]["ok"] is False and "the API key" in answer["keychain"]["message"]
    assert "token" in answer["removed"] and not (d.config.paths.home / "token").exists()


async def test_models_go_only_when_asked_and_only_this_apps(
    eraser: tuple[Daemon, FakeAgent, Exits],
) -> None:
    d, _, _ = eraser
    speech = VoiceSettings.from_config(d.config).model_repos()[0]
    listed = catalog.load_catalog().models[-1].id
    chosen = d.config.brain.local_model
    ours = sorted({speech, listed, chosen})
    for n, repo in enumerate(ours):
        model(repo, 1000 * (n + 1))
    model("someone/other-model", 5000)
    async with client(d) as http:
        preview = (await http.get("/api/delete-all")).json()
        answer = (await http.post("/api/delete-all", json={**CONFIRM, "models": True})).json()
    assert preview["home"] == os.path.realpath(d.config.paths.home)
    assert sorted(m["repo"] for m in preview["models"]) == ours
    assert preview["models_bytes"] == sum(1000 * (n + 1) for n in range(len(ours)))
    assert sorted(answer["models"]["removed"]) == ours
    assert answer["models"]["freed_bytes"] == preview["models_bytes"]
    assert not any(on_disk(repo) for repo in ours)
    assert on_disk("someone/other-model")


async def test_models_stay_unless_asked(eraser: tuple[Daemon, FakeAgent, Exits]) -> None:
    d, _, _ = eraser
    chosen = d.config.brain.local_model
    model(chosen, 1000)
    async with client(d) as http:
        answer = (await http.post("/api/delete-all", json={**CONFIRM, "models": False})).json()
    assert answer["models"] is None and on_disk(chosen)


async def test_models_must_be_true_or_false(eraser: tuple[Daemon, FakeAgent, Exits]) -> None:
    d, _, _ = eraser
    async with client(d) as http:
        answer = await http.post("/api/delete-all", json={**CONFIRM, "models": "yes"})
    assert answer.status_code == 400 and not d.erased


# --- What it covers, and who can reach it --------------------------------------------------------


def test_every_item_a_backup_holds_is_removed(config: Config) -> None:
    files, folders = erase.owned(config)
    assert set(backups.items(config)) <= files | folders
    assert backups.folder(config).name in folders
    assert config.paths.token.name in files and config.paths.logs.name in folders


def test_data_kept_outside_the_folder_is_named_not_removed(tmp_path: Path) -> None:
    from vision.core.config import load_config

    home = tmp_path / "home"
    home.mkdir()
    logs = tmp_path / "var-logs"
    logs.mkdir()
    (home / "config.toml").write_text(f'[paths]\nlogs = "{logs}"\n')
    config = load_config(home)
    files, folders = erase.owned(config)
    assert erase.elsewhere(config) == [str(logs)]
    erase.clear(home, files, folders)
    assert logs.is_dir() and not home.exists()


def test_it_is_no_tool() -> None:
    """Only the window's route leads to it: no tool in the catalog or the gate's tiers names it, and
    nothing but the settings routes and service imports it or calls the eraser."""
    words = ("delete_all", "erase", "delete-all", "wipe")
    assert not [name for name in load_catalog() if any(w in name for w in words)]
    assert not [name for name in GateConfig().tiers if any(w in name for w in words)]
    allowed = {("settings", "routes.py"), ("settings", "service.py"), ("settings", "erase.py")}
    for path in Path(erase.__file__).parents[1].rglob("*.py"):
        if (path.parent.name, path.name) in allowed:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.strip()
            assert not (code.startswith(("from ", "import ")) and "erase" in code), (path, code)
            assert ".eraser" not in code and "delete-all" not in code, (path, code)
