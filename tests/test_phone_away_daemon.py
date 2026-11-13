"""The real daemon (fake brain) against the local fake of Discord, with presence faked:
what the owner types on the phone is answered there and kept in the app; what they type
at the Mac stays at the Mac; job and automation results reach the phone always by
default, and under "when away" only while away; `send_to_phone`; and retries."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from conftest import free_port, served
from settings_fakes import client
from test_phone_daemon import OWNER, connect_and_pair, keychain, until  # noqa: F401  (keychain is a fixture)
from test_phone_discord import TOKEN, serve

from vision.app import Daemon
from vision.core.config import Config
from vision.core.events import InputText, Notice
from vision.jobs import Job
from vision.remote.discord import API_ENV
from vision.remote.outbox import DROPPED
from vision.testing.fake_discord import API, FakeDiscord
from vision.testing.fakes import DEFAULT_REPLY, FakePresenceReader

REST_TRIES = 4
"""How often the REST client itself tries one call (`vision.remote.discord.rest.MAX_TRIES`)."""


@pytest.fixture
async def fake() -> AsyncIterator[FakeDiscord]:
    async with serve(FakeDiscord(token=TOKEN)) as f:
        yield f


@pytest.fixture
async def daemon(
    config: Config, fake: FakeDiscord, keychain: dict[tuple[str, str], str], monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> AsyncIterator[Daemon]:
    monkeypatch.setenv(API_ENV, fake.base_url + API)
    async with served(Daemon(config, fake_brain=True, port=free_port())) as d:
        await connect_and_pair(d, fake)
        yield d


def texts(fake: FakeDiscord) -> list[str]:
    return [m.get("content", "") for m in fake.sent()]


def a_job(job_id: str, via: str = "text") -> Job:
    return Job(job_id, "Check the tests", "Run them.", "checker", None, "done", "host", None, False, time.time(), via=via, result="All pass.")


async def reported(d: Daemon, job: Job) -> None:
    """Hand the job to the daemon's reporter and wait for the host's turn about it to be logged."""
    d.board.listeners[-1](job)
    for _ in range(500):
        if any(t.source == "job" and job.id in t.user_text for t in await d.components.memory.history(20)):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the job was not reported")


@pytest.mark.parametrize("away", [False, True], ids=["present", "away"])
async def test_a_job_result_under_when_away(daemon: Daemon, fake: FakeDiscord, stand_in_presence: FakePresenceReader, away: bool) -> None:
    async with client(daemon) as http:
        await http.patch("/api/phone", json={"notify": {"jobs": "away"}})
    stand_in_presence.locked = away
    before = len(fake.sent())
    await reported(daemon, a_job("j1"))
    await asyncio.sleep(0.3)
    sent = texts(fake)[before:]
    assert sent == ([DEFAULT_REPLY] if away else [])


@pytest.mark.parametrize("away", [False, True], ids=["present", "away"])
async def test_an_automation_result_under_when_away(daemon: Daemon, fake: FakeDiscord, stand_in_presence: FakePresenceReader, away: bool) -> None:
    async with client(daemon) as http:
        await http.patch("/api/phone", json={"notify": {"automations": "away"}})
        stand_in_presence.locked = away
        made = (await http.post("/api/automations", json={"name": "Morning", "instruction": "Read me the weather.", "schedule": {"kind": "daily", "time": "07:00"}})).json()
        before = len(fake.sent())
        await http.post(f"/api/automations/{made['automation']['id']}/run")
    await until(lambda: bool(daemon.automations.all()[0].results))
    await asyncio.sleep(0.3)
    sent = [t for t in texts(fake)[before:] if t.startswith("Automation")]
    assert len(sent) == (1 if away else 0)


async def test_send_to_phone_goes_now_while_present(daemon: Daemon, fake: FakeDiscord) -> None:
    result = await daemon.components.tools.call("send_to_phone", {"text": "The train leaves at 18:42."})
    assert result.ok and result.content == "Sent to the owner's phone."
    assert texts(fake)[-1] == "The train leaves at 18:42."


async def test_a_phone_message_is_answered_on_the_phone_and_kept_in_the_app(daemon: Daemon, fake: FakeDiscord) -> None:
    before = len(fake.sent())
    await fake.dm(OWNER, "What is on today?")
    await until(lambda: DEFAULT_REPLY in texts(fake)[before:])
    (last,) = [t for t in await daemon.components.memory.history(5) if t.user_text == "What is on today?"]
    assert last.source == "phone" and last.reply == DEFAULT_REPLY
    assert texts(fake)[before:].count(DEFAULT_REPLY) == 1


@pytest.mark.parametrize("away", [False, True], ids=["present", "away"])
async def test_what_is_typed_at_the_mac_is_answered_only_at_the_mac(
    daemon: Daemon, fake: FakeDiscord, stand_in_presence: FakePresenceReader, away: bool
) -> None:
    before = len(fake.sent())
    daemon.bus.publish(InputText(text="Summarise the notes."))
    await until(lambda: daemon.session is not None and daemon.session.busy)
    stand_in_presence.locked = away  # even when the owner walks away before the reply is done
    await daemon.session.wait_idle()
    await asyncio.sleep(0.3)
    turns = await daemon.components.memory.history(5)
    assert turns[-1].source == "text" and turns[-1].reply == DEFAULT_REPLY
    assert texts(fake)[before:] == []


async def test_by_default_a_job_and_an_automation_reach_the_phone_while_present(daemon: Daemon, fake: FakeDiscord) -> None:
    before = len(fake.sent())
    await reported(daemon, a_job("j9"))
    async with client(daemon) as http:
        made = (await http.post("/api/automations", json={"name": "Morning", "instruction": "Read me the weather.", "schedule": {"kind": "daily", "time": "07:00"}})).json()
        await http.post(f"/api/automations/{made['automation']['id']}/run")
    await until(lambda: any(t.startswith("Automation") for t in texts(fake)[before:]))
    assert DEFAULT_REPLY in texts(fake)[before:]


async def test_a_message_that_failed_arrives_on_a_later_try(daemon: Daemon, fake: FakeDiscord) -> None:
    daemon.phone.channel.outbox.retry_s = (0.05, 0.05, 0.05)
    fake.rate_limit_next = REST_TRIES * 2  # the first try and the first retry fail
    result = await daemon.components.tools.call("send_to_phone", {"text": "Second time lucky."})
    assert "could not be reached" in result.content
    await until(lambda: "Second time lucky." in texts(fake))
    assert texts(fake).count("Second time lucky.") == 1


async def test_a_message_that_never_arrives_is_dropped_with_a_notice(daemon: Daemon, fake: FakeDiscord) -> None:
    daemon.phone.channel.outbox.retry_s = (0.05, 0.05, 0.05)
    fake.rate_limit_next = REST_TRIES * 4
    async with daemon.bus.subscribe({Notice.TYPE}) as notices:
        await daemon.components.tools.call("send_to_phone", {"text": "Never arrives."})
        notice = await asyncio.wait_for(notices.__anext__(), 10)
    assert isinstance(notice, Notice) and notice.text.startswith(DROPPED)
    await asyncio.sleep(0.3)
    assert not any(DROPPED in t for t in texts(fake)) and "Never arrives." not in texts(fake)


async def test_a_job_from_the_phone_reports_there_while_present_and_only_once(daemon: Daemon, fake: FakeDiscord) -> None:
    before = len(fake.sent())
    await reported(daemon, a_job("j2", via="phone"))
    await asyncio.sleep(0.3)
    assert texts(fake)[before:] == [DEFAULT_REPLY]
