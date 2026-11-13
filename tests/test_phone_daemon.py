"""The phone channel in the real daemon (fake brain), against the local fake of Discord."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator

import keyring
import pytest
from conftest import free_port, served
from image_fixtures import SECRET, jpeg_with_location
from settings_fakes import client, use
from test_phone_discord import TOKEN, serve

from vision.app import Daemon
from vision.core.config import Config
from vision.core.events import GateDecision, Notice, UserUtterance
from vision.remote.discord import API_ENV
from vision.remote.token import KEYRING_ACCOUNT
from vision.testing.fake_discord import API, FakeDiscord
from vision.testing.fakes import DEFAULT_REPLY

OWNER = "111"


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[tuple[str, str], str]]:
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, a: store.get((s, a)))
    monkeypatch.setattr(keyring, "set_password", lambda s, a, v: store.__setitem__((s, a), v))
    monkeypatch.setattr(keyring, "delete_password", lambda s, a: store.pop((s, a), None))
    yield store


@pytest.fixture
async def fake() -> AsyncIterator[FakeDiscord]:
    async with serve(FakeDiscord(token=TOKEN)) as f:
        yield f


@pytest.fixture
async def daemon(
    config: Config, fake: FakeDiscord, keychain: dict[tuple[str, str], str], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Daemon]:
    monkeypatch.setenv(API_ENV, fake.base_url + API)
    async with served(Daemon(config, fake_brain=True, port=free_port())) as d:
        yield d


async def until(predicate: Callable[[], object], seconds: float = 10.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


async def connect_and_pair(d: Daemon, fake: FakeDiscord) -> None:
    async with client(d) as http:
        stored = (await http.post("/api/phone/token", json={"token": TOKEN})).json()
        assert stored == {"stored": True, "verdict": "accepted", "bot": "Vision Bot"}
        await until(lambda: d.phone.connection == "online")
        code = (await http.post("/api/phone/pairing")).json()["code"]
    await fake.dm(OWNER, code)
    await until(lambda: d.phone.state.paired)


def audits(config: Config) -> list[tuple[str, str, str]]:
    with sqlite3.connect(config.paths.log_db) as db:
        return list(db.execute("SELECT tool, decision, result FROM audit ORDER BY id"))


async def test_pair_then_talk_end_to_end(daemon: Daemon, fake: FakeDiscord) -> None:
    await connect_and_pair(daemon, fake)
    assert fake.sent()[-1]["content"].startswith("Paired.")
    async with daemon.bus.subscribe({UserUtterance.TYPE}) as said:
        await fake.dm(OWNER, "What can you do?")
        utterance = await asyncio.wait_for(said.__anext__(), 5)
    assert isinstance(utterance, UserUtterance) and utterance.source == "phone"
    await until(lambda: any(DEFAULT_REPLY.split()[0] in m["content"] for m in fake.sent()[1:]))
    turns = await daemon.components.memory.history(5)
    assert turns[-1].source == "phone" and turns[-1].user_text == "What can you do?"
    assert any(e["kind"] == "typing" for e in fake.log)


async def test_a_gated_tool_is_approved_with_a_button(daemon: Daemon, fake: FakeDiscord) -> None:
    await connect_and_pair(daemon, fake)
    daemon.config.gate.tiers["remember"] = "ask"
    call = asyncio.create_task(daemon.components.tools.call("remember", {"text": "The plants need water."}))
    await until(lambda: any("components" in m for m in fake.sent()))
    asked = next(m for m in fake.sent() if "components" in m)
    yes = asked["components"][0]["components"][0]["custom_id"]
    assert "The plants need water." in asked["content"]
    await fake.press(OWNER, asked["id"], yes)
    result = await asyncio.wait_for(call, 10)
    assert result.ok
    await until(lambda: fake.sent("edit"))
    assert "Approved from the phone" in fake.sent("edit")[-1]["content"]
    assert [(t, d) for t, d, _ in audits(daemon.config)] == [("remember", "allow")]


async def test_shell_waits_for_the_mac(daemon: Daemon, fake: FakeDiscord) -> None:
    await connect_and_pair(daemon, fake)
    call = asyncio.create_task(daemon.components.tools.call("shell", {"command": "echo hello"}))
    await until(lambda: any("echo hello" in m.get("content", "") for m in fake.sent()))
    asked = next(m for m in fake.sent() if "echo hello" in m.get("content", ""))
    assert "components" not in asked and "at the Mac" in asked["content"]
    request_id = next(iter(daemon.snapshot.gate_pending))
    await fake.press(OWNER, asked["id"], f"gate:{request_id}:allow")
    await until(lambda: fake.sent("ack"))
    assert not call.done()
    daemon.bus.publish(GateDecision(id=request_id, decision="deny"))
    assert not (await asyncio.wait_for(call, 10)).ok


async def test_notices_reach_the_phone(daemon: Daemon, fake: FakeDiscord) -> None:
    await connect_and_pair(daemon, fake)
    daemon.bus.publish(Notice(level="warn", text="Voice is off."))
    await until(lambda: any(m["content"] == "Warning: Voice is off." for m in fake.sent()))


async def test_a_stranger_gets_nothing(daemon: Daemon, fake: FakeDiscord) -> None:
    await connect_and_pair(daemon, fake)
    before = len(await daemon.components.memory.history(50))
    await fake.dm("222", "status")
    await until(lambda: any(r == "not the paired owner" for _, _, r in audits(daemon.config)))
    assert len(await daemon.components.memory.history(50)) == before
    assert "private assistant" in fake.sent()[-1]["content"]


async def test_routes_never_return_the_token(daemon: Daemon, fake: FakeDiscord) -> None:
    async with client(daemon) as http:
        refused = await http.post("/api/phone/token", json={"token": TOKEN[:-2] + "zz"})
        assert refused.status_code == 400 and TOKEN[:-2] not in refused.text
        await http.post("/api/phone/token", json={"token": TOKEN})
        view = await http.get("/api/phone")
        verify = await http.post("/api/phone/token/verify")
        unauthorised = await http.get("/api/phone", headers={"Authorization": "Bearer nope"})
    assert TOKEN not in view.text and TOKEN not in verify.text
    assert view.json()["token"] == {"stored": True} and verify.json() == {"verdict": "accepted", "bot": "Vision Bot"}
    assert unauthorised.status_code == 401
    assert TOKEN not in (daemon.config.paths.home / "phone.json").read_text()


async def test_settings_change_and_refuse(daemon: Daemon, fake: FakeDiscord) -> None:
    async with client(daemon) as http:
        view = (await http.get("/api/phone")).json()
        assert view["connection"] == "no_token" and "shell" not in view["phone_tools"]
        assert view["mac_only"] == ["shell"]
        changed = (await http.patch("/api/phone", json={"notify": {"warnings": "never"}, "speak_on_mac": True, "phone_tools": ["remember"]})).json()
        shell = await http.patch("/api/phone", json={"phone_tools": ["shell"]})
        odd = await http.patch("/api/phone", json={"volume": 11})
        off = (await http.patch("/api/phone", json={"enabled": False})).json()
        paired_code = await http.delete("/api/phone/pairing")
    assert changed["notify"]["warnings"] == "never" and changed["speak_on_mac"] is True and changed["phone_tools"] == ["remember"]
    assert shell.status_code == 400 and "only ever approved at the Mac" in shell.json()["detail"]
    assert odd.status_code == 400
    assert off["connection"] == "off" and paired_code.json()["paired"] is None


async def test_start_over_unpairs_and_keeps_the_token_unless_asked(
    daemon: Daemon, fake: FakeDiscord, keychain: dict[tuple[str, str], str]
) -> None:
    await connect_and_pair(daemon, fake)
    use(daemon)
    async with client(daemon) as http:
        first = (await http.post("/api/reset", json={"level": "everything"})).json()
        assert "phone.json" in first["backup"]["files"]
        backed_up = daemon.config.paths.home / "backups" / first["backup"]["id"] / "phone.json"
        assert json.loads(backed_up.read_text())["phone"]["owner_id"] == OWNER
        assert TOKEN not in backed_up.read_text()
        assert not daemon.phone.state.paired
        assert any(a == KEYRING_ACCOUNT for _, a in keychain)
        await until(lambda: daemon.phone.connection == "online")
        await http.post("/api/reset", json={"level": "everything", "remove_key": True})
    assert not any(a == KEYRING_ACCOUNT for _, a in keychain)
    assert daemon.phone.connection == "no_token"


async def test_an_image_from_the_phone_end_to_end(daemon: Daemon, fake: FakeDiscord) -> None:
    await connect_and_pair(daemon, fake)
    async with daemon.bus.subscribe({UserUtterance.TYPE}) as said:
        await fake.dm(OWNER, "Look at this", attach=[("IMG_0001.jpg", "image/jpeg", jpeg_with_location())])
        utterance = await asyncio.wait_for(said.__anext__(), 10)
    assert isinstance(utterance, UserUtterance) and utterance.source == "phone"
    (image,) = utterance.images
    stored = daemon.config.paths.images / f"{image.id}.jpg"
    assert stored.is_file() and SECRET not in stored.read_bytes()
    turns: list[dict[str, object]] = []
    async with client(daemon) as http:
        for _ in range(200):
            turns = (await http.get("/api/history")).json()["turns"]
            if turns and turns[-1]["source"] == "phone":
                break
            await asyncio.sleep(0.05)
    assert turns[-1]["images"] == [{"id": image.id, "width": 40, "height": 30}]
    assert turns[-1]["user_text"] == "Look at this"
