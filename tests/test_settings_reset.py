"""Reset at three levels and restore, always with a backup first; the daemon follows."""

from __future__ import annotations

import json
import time
import tomllib

import pytest
from settings_fakes import FakeOutside, client, use

from vision.app import Daemon
from vision.core.interfaces import TurnRecord
from vision.settings import backups


def turn(text: str) -> TurnRecord:
    now = time.time()
    return TurnRecord("t-" + text, now, now, "text", text, "ok.", "ok", "fake", "fake-1")


async def test_settings_reset_backs_up_and_applies(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        await http.patch(
            "/api/settings", json={"assistant": {"name": "Ada"}, "budget": {"cap_usd": 10}}
        )
        answer = (await http.post("/api/reset", json={"level": "settings"})).json()
        listed = (await http.get("/api/backups")).json()["backups"]
    backup = answer["backup"]
    assert backup["level"] == "settings" and backup["files"] == ["config.toml"]
    assert answer["restart"] is False
    assert listed == [backup]
    saved = daemon.config.paths.home / "backups" / backup["id"]
    assert tomllib.loads((saved / "config.toml").read_text())["assistant"]["name"] == "Ada"
    assert json.loads((saved / "manifest.json").read_text())["files"] == ["config.toml"]
    assert not daemon.config.paths.config_file.exists()
    assert daemon.config.assistant.name == "Vision"
    assert daemon.components.budget.status().cap_usd == 150.0


async def test_model_changes_and_restarts(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        await http.patch("/api/settings", json={"models": {"talk": "claude-sonnet-5-5"}})
        reset = (await http.post("/api/reset", json={"level": "settings"})).json()
        after_reset = (await http.get("/api/settings")).json()
        restored = (await http.post(f"/api/backups/{reset['backup']['id']}/restore")).json()
        after_restore = (await http.get("/api/settings")).json()
    # The reset brings back the model the brain is running: nothing to restart.
    assert reset["restart"] is False and after_reset["restart_pending"] == []
    assert restored["restart"] is True and restored["restored"] == ["config.toml"]
    assert after_restore["restart_pending"] == ["models.talk"]
    assert after_restore["models"]["talk"] == "claude-sonnet-5-5"


async def test_house_reset_reloads_the_house(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        await http.post("/api/house/rooms", json={"name": "Den", "agent": "maker", "at": [4, 1]})
        before = (await http.get("/api/house")).json()
        answer = (await http.post("/api/reset", json={"level": "house"})).json()
        after = (await http.get("/api/house")).json()
    assert "den" in {r["id"] for r in before["rooms"]}
    assert "den" not in {r["id"] for r in after["rooms"]}
    assert after["revision"] > before["revision"]
    assert answer["backup"]["files"] == ["house.toml"] and answer["restart"] is False
    assert "Den" not in daemon.config.paths.house_file.read_text()


async def test_everything_reset_and_restore(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(key="sk-ant-old"))
    memory = daemon.components.memory
    await memory.remember("The boat is blue.")
    await memory.log_turn(turn("hello"))
    daemon.components.budget.record("claude-opus-5-5", 1_000_000, 0)
    async with client(daemon) as http:
        await http.patch("/api/settings", json={"setup": {"completed": True}})
        answer = (await http.post(
            "/api/reset", json={"level": "everything", "remove_key": True}
        )).json()
        settings = (await http.get("/api/settings")).json()
    backup = answer["backup"]
    assert set(backup["files"]) == {"config.toml", "house.toml", "house", "log.db", "budget.json"}
    assert answer["restart"] is True and "Keychain" in answer["message"]
    assert fake.key is None and "delete_key" in fake.calls
    assert settings["setup"] == {"completed": False, "first_run": True}
    assert settings["budget"]["spent_usd"] == 0
    assert await memory.history(10) == []
    assert "The boat is blue." not in memory.core()
    assert (daemon.config.paths.house / "agents" / "host.md").is_file()
    await memory.log_turn(turn("after"))

    async with client(daemon) as http:
        restored = (await http.post(f"/api/backups/{backup['id']}/restore")).json()
        listed = (await http.get("/api/backups")).json()["backups"]
    assert set(restored["restored"]) == set(backup["files"])
    assert restored["backup"]["level"] == "restore" and restored["restart"] is True
    assert [b["level"] for b in listed] == ["restore", "everything"]
    assert [t.user_text for t in await memory.history(10)] == ["hello"]
    assert "The boat is blue." in memory.core()
    assert daemon.components.budget.status().spent_usd == pytest.approx(4.0)
    assert getattr(daemon.config.assistant, "setup_completed", False) is True


async def test_key_is_kept_unless_asked(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(key="sk-ant-old"))
    async with client(daemon) as http:
        await http.post("/api/reset", json={"level": "everything"})
    assert fake.key == "sk-ant-old" and "delete_key" not in fake.calls


@pytest.mark.parametrize(
    "backup_id", ["nope", "20261112-130500-hack", "...", "20261112-130500-settings-x"]
)
async def test_unknown_or_tricky_ids_are_404(daemon: Daemon, backup_id: str) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.post(f"/api/backups/{backup_id}/restore")
    assert answer.status_code == 404


def test_ids_cannot_escape_the_backups_folder() -> None:
    assert not backups.ID.match("../20261112-130500-settings")
    assert not backups.ID.match("20261112-130500-settings/../../x")


async def test_bad_reset_requests(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        level = await http.post("/api/reset", json={"level": "all"})
        flag = await http.post("/api/reset", json={"level": "house", "remove_key": "yes"})
    assert level.status_code == flag.status_code == 400
    assert not (daemon.config.paths.home / "backups").exists()
