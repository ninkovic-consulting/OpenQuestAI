"""What reaches the phone, by kind and choice, with the owner at the Mac or away; the
old switches; nothing twice; retries and drops; and `send_to_phone`. Anything the
assistant does by itself reaches the phone by default, whether the owner is there or not."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from phone_fakes import CHAT, FakeDecoder, FakeEars, FakeHost, FakeTransport, MemoryTokens, Rig, rig, settle

from vision.core.events import AutomationFinished, AutomationStarted, GateRequest, Notice
from vision.remote import store
from vision.remote.outbox import DROPPED, Outbox
from vision.gate.tools import ToolFailure
from vision.remote.rules import CHOICES, DEFAULTS, KINDS, Choice, Kind, read_choice
from vision.remote.service import Phone
from vision.remote.store import PhoneState
from vision.remote.tools import build_tools
from vision.remote.transport import Unreachable


def messages(r: Rig) -> int:
    return len(r.transport.sent) + len(r.transport.buttons)


async def automation(r: Rig) -> None:
    await r.channel.notifier.handle(AutomationFinished(id="a1", name="Morning", status="ok", reply="Rain."))


async def warning(r: Rig) -> None:
    await r.channel.notifier.handle(Notice(level="warn", text="Voice is off."))


async def approval(r: Rig) -> None:
    req = GateRequest(id="r1", tool="open_url", summary="Open a link", detail="https://example.org", expires_at=time.time() + 60)
    await r.channel.notifier.handle(req)


async def job(r: Rig) -> None:
    await r.channel.notifier.job_result("j1", "Tock: the tests pass.", from_phone=False, started_at=time.time())


TRIGGERS: dict[str, Callable[[Rig], Awaitable[None]]] = {
    "automations": automation,
    "warnings": warning,
    "approvals": approval,
    "jobs": job,
}


@pytest.mark.parametrize("away", [False, True], ids=["present", "away"])
@pytest.mark.parametrize("choice", CHOICES)
@pytest.mark.parametrize("kind", sorted(TRIGGERS))
async def test_each_kind_follows_its_choice(kind: Kind, choice: Choice, away: bool) -> None:
    r = rig()
    setattr(r.state, f"notify_{kind}", choice)
    if away:
        r.host.leave(since=time.time() - 60)
    await TRIGGERS[kind](r)
    expected = choice == "always" or (choice == "away" and away)
    assert messages(r) == (1 if expected else 0)


def test_the_defaults_for_a_new_pairing_send_everything_always() -> None:
    state = PhoneState()
    assert {k: getattr(state, f"notify_{k}") for k in KINDS} == DEFAULTS == dict.fromkeys(KINDS, "always")


@pytest.mark.parametrize("kind", sorted(TRIGGERS))
async def test_by_default_each_kind_reaches_the_phone_while_the_owner_is_at_the_mac(kind: str) -> None:
    r = rig()
    assert not r.host.seen.away
    await TRIGGERS[kind](r)
    assert messages(r) == 1


def test_old_switches_read_as_always_or_never(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "phone.json"
    old = {"notify_automations": True, "notify_warnings": False, "notify_approvals": True, "notify_jobs": False, "owner_id": "111"}
    path.write_text(json.dumps({"version": 1, "phone": old}))
    state = store.load(path)
    assert (state.notify_automations, state.notify_warnings, state.notify_approvals, state.notify_jobs) == ("always", "never", "always", "never")
    assert state.notify_assistant == "always" and state.owner_id == "111"
    store.save(path, state)
    saved = json.loads(path.read_text())
    assert saved["version"] == 2 and saved["phone"]["notify_warnings"] == "never"
    assert store.load(path) == state


def test_a_strange_choice_moves_the_file_aside(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "phone.json"
    path.write_text(json.dumps({"version": 2, "phone": {"notify_jobs": "sometimes", "owner_id": "111"}}))
    assert not store.load(path).paired and (tmp_path / "phone.json.broken").exists()
    with pytest.raises(TypeError):
        read_choice("loud")


# ---------------------------------------------------------------- jobs


async def test_a_job_from_the_phone_reports_there_even_while_present() -> None:
    r = rig()
    r.state.notify_jobs = "away"
    assert not r.host.seen.away
    await r.channel.notifier.job_result("j1", "Done.", from_phone=False, started_at=time.time())
    await r.channel.notifier.job_result("j2", "Done too.", from_phone=True, started_at=time.time())
    assert r.transport.texts() == ["Done too."]


async def test_a_job_is_reported_once() -> None:
    r = rig()
    r.state.notify_jobs = "always"
    for _ in range(3):
        await r.channel.notifier.job_result("j1", "Done.", from_phone=True, started_at=time.time())
    assert r.transport.texts() == ["Done."]


# ---------------------------------------------------------------- send_to_phone


@dataclass
class PhoneRig:
    """A real `Phone` over the fakes, paired and online."""

    phone: Phone
    host: FakeHost
    transport: FakeTransport

    @property
    def state(self) -> PhoneState:
        return self.phone.state

    async def tool(self, text: str) -> str:
        (tool,) = build_tools(self.phone)
        return await tool.run({"text": text})


def phone_rig(tmp_path: Path) -> PhoneRig:
    host, transport = FakeHost(), FakeTransport()
    phone = Phone(host, tmp_path, tokens=MemoryTokens("t"), transports=lambda token: transport, ears=FakeEars(), decoders=[FakeDecoder()])  # type: ignore[arg-type]
    phone.state.owner_id, phone.state.owner_name, phone.state.chat_id = "111", "Owner", CHAT
    phone.connection = "online"
    phone._transport = transport  # what `_keep_connected` holds while connected
    return PhoneRig(phone, host, transport)


async def test_the_tool_sends_now_whatever_the_away_state(tmp_path: Path) -> None:
    p = phone_rig(tmp_path)
    assert not p.host.seen.away
    assert await p.tool("The address is 12 Elm Street.") == "Sent to the owner's phone."
    p.state.notify_assistant = "always"
    p.host.leave(since=time.time())
    assert await p.tool("Leaving now.") == "Sent to the owner's phone."
    assert p.transport.texts() == ["The address is 12 Elm Street.", "Leaving now."]


@pytest.mark.parametrize(
    ("setup", "words"),
    [
        (lambda p: p.state.unpair(), "No phone is paired"),
        (lambda p: setattr(p.state, "enabled", False), "turned off in Settings, Phone"),
        (lambda p: setattr(p.phone, "connection", "no_token"), "not working"),
        (lambda p: setattr(p.state, "notify_assistant", "never"), "Messages from the assistant to the phone are turned off"),
    ],
)
async def test_the_tool_says_plainly_why_nothing_went(tmp_path: Path, setup: Callable[[PhoneRig], object], words: str) -> None:
    p = phone_rig(tmp_path)
    setup(p)
    assert words in await p.tool("Hello.")
    assert p.transport.sent == []


async def test_the_tool_says_when_discord_is_unreachable_and_keeps_trying(tmp_path: Path) -> None:
    p = phone_rig(tmp_path)
    p.phone._transport = None  # reconnecting
    p.phone.channel.outbox.retry_s = (0.01,)
    words = await p.tool("Hello.")
    assert "could not be reached" in words and "tried again" in words
    p.phone._transport = p.transport
    await settle()
    assert p.transport.texts() == ["Hello."]


async def test_the_tool_refuses_nothing_and_too_much(tmp_path: Path) -> None:
    p = phone_rig(tmp_path)
    with pytest.raises(ToolFailure):
        await p.tool("  ")
    with pytest.raises(ToolFailure):
        await p.tool("x" * 1501)


async def test_what_the_tool_sent_is_not_sent_again_as_the_turns_result(tmp_path: Path) -> None:
    p = phone_rig(tmp_path)
    notifier = p.phone.channel.notifier
    p.state.notify_jobs = "always"
    started = time.time() - 1
    await notifier.handle(AutomationStarted(id="a1", name="Ping me", ts=started))
    await p.tool("Time to leave for the train.")
    await notifier.handle(AutomationFinished(id="a1", name="Ping me", status="ok", reply="I sent it."))
    await notifier.job_result("j1", "I sent it.", from_phone=True, started_at=started)
    assert p.transport.texts() == ["Time to leave for the train."]
    await notifier.handle(AutomationStarted(id="a1", name="Ping me"))
    await notifier.handle(AutomationFinished(id="a1", name="Ping me", status="ok", reply="Next run, no ping."))
    assert len(p.transport.texts()) == 2


def test_the_tool_is_free_and_the_hosts_alone(config) -> None:  # type: ignore[no-untyped-def]
    from vision.house.tools import load_catalog
    from vision.residents.abilities import BASE, EXTRA

    assert config.gate.tiers["send_to_phone"] == "free"
    entry = load_catalog()["send_to_phone"]
    assert entry.built_in and not entry.resident
    assert "send_to_phone" not in BASE and all("send_to_phone" not in tools for tools in EXTRA.values())


# ---------------------------------------------------------------- retries and drops


@dataclass
class FlakyTransport(FakeTransport):
    failures: int = 0
    tries: int = 0

    async def send(self, chat_id: str, text: str) -> str:
        self.tries += 1
        if self.failures > 0:
            self.failures -= 1
            raise Unreachable("Discord answered 503.")
        return await super().send(chat_id, text)


def flaky(failures: int) -> tuple[Rig, FlakyTransport, Outbox]:
    r = rig()
    transport = FlakyTransport(failures=failures)
    r.link.current = lambda: transport
    outbox = Outbox(r.link, retry_s=(0.01, 0.01, 0.01))
    return r, transport, outbox


async def test_a_message_that_did_not_arrive_is_tried_again() -> None:
    r, transport, outbox = flaky(failures=2)
    assert await outbox.send("job:j1", "Done.") == "retrying"
    await settle()
    assert transport.texts() == ["Done."] and transport.tries == 3


async def test_after_a_few_tries_it_is_dropped_with_a_notice_that_stays_in_the_app() -> None:
    r, transport, outbox = flaky(failures=10)
    async with r.host.bus.subscribe({Notice.TYPE}) as notices:
        assert await outbox.send("job:j1", "Done.") == "retrying"
        notice = await asyncio.wait_for(notices.__anext__(), 2)
    assert isinstance(notice, Notice) and notice.text.startswith(DROPPED) and "4 tries" in notice.text
    assert transport.tries == 4 and transport.sent == []
    notifier_rig = rig()
    await notifier_rig.channel.notifier.handle(notice)
    assert notifier_rig.transport.sent == []  # never sent to the phone it could not reach


async def test_a_message_waiting_to_be_tried_again_is_not_sent_twice() -> None:
    r, transport, outbox = flaky(failures=1)
    assert await outbox.send("job:j1", "Done.") == "retrying"
    assert await outbox.send("job:j1", "Done.") == "duplicate"
    await settle()
    assert transport.texts() == ["Done."]


async def test_unpairing_stops_the_retries_and_closing_cancels_them() -> None:
    r, transport, outbox = flaky(failures=10)
    await outbox.send("job:j1", "Done.")
    r.state.unpair()
    await settle()
    assert transport.tries <= 2
    r2, transport2, outbox2 = flaky(failures=10)
    outbox2.retry_s = (60.0,)
    await outbox2.send("job:j2", "Done.")
    await outbox2.close()
    assert transport2.tries == 1


async def test_nothing_is_queued_before_pairing() -> None:
    r = rig(paired=False)
    outbox = Outbox(r.link)
    assert await outbox.send("job:j1", "Done.") == "unpaired"
