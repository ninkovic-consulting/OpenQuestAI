"""Images through a turn: the session, the log and history, the window's socket, and a reset."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import stat
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from image_fixtures import jpeg_with_location, png
from settings_fakes import client
from test_protocol import collect_turn, open_socket
from test_session import Rig, until

from vision.app import Daemon
from vision.attachments import ImageStore
from vision.core.config import Config
from vision.core.events import InputText, Notice, UserUtterance
from vision.core.interfaces import ImageRef, TurnRecord
from vision.core.session import IMAGE_GONE, Session
from vision.memory import make_memory
from vision.testing.fakes import FakeBrain, FakeToolHost


class ImageRig(Rig):
    def __init__(self, folder: Path, tools: FakeToolHost | None = None) -> None:
        super().__init__(FakeBrain(["I see it."], delay=0))
        self.store = ImageStore(folder)
        self.session = Session(
            self.bus, self.brain, self.speaker, self.memory, tools or FakeToolHost(), images=self.store
        )


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[ImageRig]:
    r = ImageRig(tmp_path / "images")
    task = asyncio.create_task(r.session.run())
    await asyncio.sleep(0)
    yield r
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_typed_text_with_images_reaches_the_brain_and_the_log(rig: ImageRig) -> None:
    a, b = rig.store.add(png(30, 20)), rig.store.add(png(5, 5, (0, 0, 255)))
    rig.bus.publish(InputText(text="What are these?", images=[a.id, b.id]))
    await until(lambda: len(rig.memory.turns) == 1)
    await rig.session.wait_idle()
    assert rig.brain.sent == [("What are these?", False)]
    assert rig.brain.images == [(a, b)]
    (said,) = [e for e in rig.drain() if isinstance(e, UserUtterance)]
    assert [(i.id, i.width, i.height) for i in said.images] == [(a.id, 30, 20), (b.id, 5, 5)]
    assert rig.memory.turns[0].images == (ImageRef(a.id, 30, 20), ImageRef(b.id, 5, 5))


async def test_an_image_alone_is_asked_about(rig: ImageRig) -> None:
    a = rig.store.add(png(4, 4))
    rig.bus.publish(InputText(images=[a.id]))
    await until(lambda: len(rig.memory.turns) == 1)
    await rig.session.wait_idle()
    assert rig.brain.sent[0][0] == "The owner sent this image."
    assert rig.memory.turns[0].user_text == ""


async def test_a_text_turn_sends_no_images(rig: ImageRig) -> None:
    rig.bus.publish(InputText(text="hi"))
    await until(lambda: len(rig.memory.turns) == 1)
    await rig.session.wait_idle()
    assert rig.brain.images == [()] and rig.memory.turns[0].images == ()


async def test_an_image_that_is_gone_starts_no_turn(rig: ImageRig) -> None:
    a = rig.store.add(png(4, 4))
    rig.store.remove(a.id)
    rig.bus.publish(InputText(text="look", images=[a.id]))
    await until(lambda: any(isinstance(e, Notice) for e in list(rig.events._queue._queue)))  # type: ignore[attr-defined]
    notices = [e for e in rig.drain() if isinstance(e, Notice)]
    assert notices[0].text == IMAGE_GONE and notices[0].level == "warn"
    assert rig.brain.sent == [] and rig.memory.turns == []


class Waiting(FakeToolHost):
    answered: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.answered = []

    @property
    def waiting(self) -> bool:
        return True

    def answer(self, text: str) -> bool:
        self.answered.append(text)
        return True


async def test_a_message_with_images_is_never_taken_as_a_yes(tmp_path: Path) -> None:
    tools = Waiting()
    r = ImageRig(tmp_path / "images", tools)
    task = asyncio.create_task(r.session.run())
    try:
        a = r.store.add(png(4, 4))
        r.bus.publish(InputText(text="yes", images=[a.id]))
        await until(lambda: len(r.memory.turns) == 1)
        assert tools.answered == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------- the log


async def test_the_log_keeps_a_turns_images_across_a_restart(config: Config) -> None:
    refs = (ImageRef("a" * 32, 640, 480), ImageRef("b" * 32, 10, 20))
    first = make_memory(config)
    await first.start()
    await first.log_turn(TurnRecord("t1", 1.0, 2.0, "text", "two pictures", "nice", "ok", "fake", "f", images=refs))
    await first.log_turn(TurnRecord("t2", 3.0, 4.0, "text", "words only", "ok", "ok", "fake", "f"))
    await first.close()
    again = make_memory(config)
    await again.start()
    try:
        turns = await again.history(10)
    finally:
        await again.close()
    assert [t.images for t in turns] == [refs, ()]


async def test_an_older_log_gets_the_images_column(config: Config) -> None:
    config.paths.log_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(config.paths.log_db) as db:
        db.execute(
            "CREATE TABLE turns (turn_id TEXT PRIMARY KEY, started_at REAL NOT NULL, ended_at REAL NOT NULL, "
            "source TEXT NOT NULL, user_text TEXT NOT NULL, reply TEXT NOT NULL, status TEXT NOT NULL, "
            "brain TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL, "
            "output_tokens INTEGER NOT NULL, error TEXT NOT NULL)"
        )
        db.execute("INSERT INTO turns VALUES ('old', 1, 2, 'text', 'hi', 'hello', 'ok', 'fake', 'f', 0, 0, '')")
    memory = make_memory(config)
    await memory.start()
    try:
        (old,) = await memory.history(5)
    finally:
        await memory.close()
    assert old.turn_id == "old" and old.images == ()


# ---------------------------------------------------------------- the daemon


async def test_upload_send_and_see_it_in_history_after_a_restart(config: Config, daemon: Daemon) -> None:
    async with client(daemon) as http:
        image = (await http.post("/api/images", content=jpeg_with_location())).json()["image"]
    ws = await open_socket(daemon)
    try:
        await ws.send(json.dumps({"type": "input.text", "ts": 1.0, "data": {"text": "", "images": [image["id"]]}}))
        events = await collect_turn(ws)
    finally:
        await ws.close()
    said = next(e for e in events if e["type"] == "user.utterance")
    assert said["data"] == {"text": "", "source": "text", "images": [{"id": image["id"], "width": 40, "height": 30}]}
    async with client(daemon) as http:
        turns = (await http.get("/api/history")).json()["turns"]
    assert turns[-1]["images"] == [{"id": image["id"], "width": 40, "height": 30}]
    stored = config.paths.images / f"{image['id']}.jpg"
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600


async def test_a_full_reset_backs_up_and_clears_the_images(daemon: Daemon) -> None:
    async with client(daemon) as http:
        image = (await http.post("/api/images", content=png(8, 8))).json()["image"]
        answer = (await http.post("/api/reset", json={"level": "everything", "confirm": daemon.config.assistant.name})).json()
        assert (await http.get(f"/api/images/{image['id']}")).status_code == 404
    backup = daemon.config.paths.home / "backups" / answer["backup"]["id"]
    assert "images" in answer["backup"]["files"]
    assert (backup / "images" / f"{image['id']}.png").is_file()
