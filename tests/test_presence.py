"""Whether the owner is at the Mac: readings to away or present, the event, the routes and
the settings. The idle time is always faked; the real reader is only asked to fail."""

from __future__ import annotations

import asyncio

import pytest
from settings_fakes import client, use

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import PresenceChanged, UserUtterance
from vision.presence import Presence, reader
from vision.presence.reader import MacReader
from vision.testing.fakes import FakePresenceReader


def watch(config: Config, fake: FakePresenceReader, now: list[float], poll_s: float = 5.0) -> tuple[Presence, Bus]:
    bus = Bus()
    return Presence(config, bus, fake, clock=lambda: now[0], poll_s=poll_s), bus


def test_idle_past_the_away_time_is_away_from_when_the_time_ran_out(config: Config) -> None:
    fake, now = FakePresenceReader(idle_s=10.0), [1000.0]
    p, _ = watch(config, fake, now)
    assert not p.check().away and p.check().known
    fake.idle_s, now[0] = 400.0, 1390.0
    seen = p.check()
    assert seen.away and seen.reason == "idle" and seen.since == pytest.approx(1290.0)  # 1390 - 400 + 300
    fake.idle_s = 0.0
    assert not p.check().away and p.seen.since == 1390.0


@pytest.mark.parametrize(("locked", "asleep", "reason"), [(True, False, "locked"), (False, True, "asleep")])
def test_a_locked_screen_or_a_sleeping_display_is_away_at_once(config: Config, locked: bool, asleep: bool, reason: str) -> None:
    fake, now = FakePresenceReader(idle_s=2.0, locked=locked, asleep=asleep), [50.0]
    seen = watch(config, fake, now)[0].check()
    assert seen.away and seen.reason == reason and seen.since == 50.0


def test_a_mac_that_will_not_say_counts_as_present(config: Config) -> None:
    seen = watch(config, FakePresenceReader(None, None, None), [1.0])[0].check()
    assert not seen.away and not seen.known


def test_the_real_reader_reads_unknown_where_it_cannot_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader, "CORE_GRAPHICS", "/nowhere/CoreGraphics")
    assert not MacReader().read().known


def test_speech_at_the_mac_counts_as_presence(config: Config) -> None:
    fake, now = FakePresenceReader(idle_s=900.0), [5000.0]
    p, _ = watch(config, fake, now)
    assert p.check().away
    p.heard()
    assert not p.seen.away  # talking to the assistant without touching anything
    now[0] += 299
    fake.idle_s += 299
    assert not p.check().away
    now[0] += 2
    fake.idle_s += 2
    assert p.check().away


async def test_changes_are_announced_once_and_the_away_time_applies_at_once(config: Config) -> None:
    fake, now = FakePresenceReader(idle_s=100.0), [1000.0]
    p, bus = watch(config, fake, now)
    async with bus.subscribe({PresenceChanged.TYPE}) as sub:
        p.check()
        p.check()
        first = await asyncio.wait_for(sub.__anext__(), 1)
        config.presence.away_after_s = 60.0
        p.check()
        second = await asyncio.wait_for(sub.__anext__(), 1)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(sub.__anext__(), 0.05)
    assert isinstance(first, PresenceChanged) and not first.away and first.away_after_s == 300.0
    assert isinstance(second, PresenceChanged) and second.away and second.reason == "idle" and second.away_after_s == 60.0


async def test_it_follows_the_mac_and_words_to_the_assistant(config: Config) -> None:
    fake, now = FakePresenceReader(idle_s=1000.0), [10_000.0]
    p, bus = watch(config, fake, now, poll_s=0.01)
    task = asyncio.create_task(p.run())
    try:
        await asyncio.sleep(0.05)
        assert p.seen.away
        bus.publish(UserUtterance(text="Hello from the phone", source="phone"))
        await asyncio.sleep(0.05)
        assert p.seen.away  # a message from the phone says the owner is elsewhere
        bus.publish(UserUtterance(text="Vision, what time is it?", source="voice"))
        await asyncio.sleep(0.05)
        assert not p.seen.away
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_the_daemon_serves_presence_and_says_it_in_status(daemon: Daemon, stand_in_presence: FakePresenceReader) -> None:
    async with client(daemon) as http:
        state = (await http.get("/api/state")).json()
        assert state["presence"]["away"] is False and state["presence"]["known"] is True
        stand_in_presence.locked = True
        phone = (await http.get("/api/phone")).json()
    assert phone["presence"]["away"] is True and phone["presence"]["reason"] == "locked"
    assert phone["presence"]["away_after_s"] == 300.0
    use(daemon)
    status = await daemon.components.tools.call("assistant_status", {})
    assert "The owner is away from the Mac (the screen is locked)." in status.content


async def test_status_says_when_presence_cannot_be_read(daemon: Daemon, stand_in_presence: FakePresenceReader) -> None:
    stand_in_presence.idle_s = stand_in_presence.locked = stand_in_presence.asleep = None
    use(daemon)
    status = await daemon.components.tools.call("assistant_status", {})
    assert "this Mac does not say whether anyone is using it" in status.content


async def test_the_away_time_is_checked_written_and_applied(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        low = await http.patch("/api/settings", json={"presence": {"away_after_s": 5}})
        odd = await http.patch("/api/settings", json={"presence": {"away_after_s": "soon", "colour": 1}})
        ok = await http.patch("/api/settings", json={"presence": {"away_after_s": 600}})
        phone_low = await http.patch("/api/phone", json={"away_after_s": 99_999})
        phone_ok = await http.patch("/api/phone", json={"away_after_s": 120, "notify": {"jobs": "always"}})
        phone_odd = await http.patch("/api/phone", json={"notify": {"jobs": True}})
    assert low.status_code == 400 and low.json()["detail"]["errors"][0]["field"] == "presence.away_after_s"
    assert {e["field"] for e in odd.json()["detail"]["errors"]} == {"presence.away_after_s", "presence.colour"}
    assert ok.status_code == 200 and "presence.away_after_s" in ok.json()["applied"]
    assert phone_low.status_code == 400 and "60 to 7200" in phone_low.json()["detail"]
    assert phone_ok.json()["presence"]["away_after_s"] == 120.0 and phone_ok.json()["notify"]["jobs"] == "always"
    assert phone_odd.status_code == 400 and "always, away, never" in phone_odd.json()["detail"]
    assert daemon.config.presence.away_after_s == 120.0
    assert "away_after_s = 120" in daemon.config.paths.config_file.read_text()
