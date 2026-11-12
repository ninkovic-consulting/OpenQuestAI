"""Notifications out, each behind its switch, and approvals with buttons."""

from __future__ import annotations

import asyncio
import time

import pytest
from phone_fakes import CHAT, STRANGER, press, rig

from vision.core.bus import Subscription
from vision.core.events import (
    AutomationFinished,
    GateDecision,
    GateRequest,
    GateResolved,
    Notice,
)
from vision.remote.approvals import DETAIL_ROOM, GONE, button_data, parse_data


async def nothing_on(sub: Subscription) -> None:
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(sub.__anext__(), 0.05)


def request(tool: str = "open_url", detail: str = "https://example.org", rid: str = "r1") -> GateRequest:
    return GateRequest(id=rid, tool=tool, summary="Open a link", detail=detail, expires_at=time.time() + 60)


async def test_automation_results_follow_their_switch() -> None:
    r = rig()
    done = AutomationFinished(id="a1", name="Morning", status="ok", reply="Rain until ten.")
    await r.channel.notifier.handle(done)
    assert r.transport.sent == [(CHAT, "Automation “Morning” ran.\n\nRain until ten.")]
    r.state.notify_automations = False
    await r.channel.notifier.handle(done)
    assert len(r.transport.sent) == 1


async def test_only_warnings_and_errors_follow_their_switch() -> None:
    r = rig()
    await r.channel.notifier.handle(Notice(level="info", text="Hello."))
    await r.channel.notifier.handle(Notice(level="warn", text="Voice is off."))
    await r.channel.notifier.handle(Notice(level="error", text="No brain could answer."))
    assert r.transport.texts() == ["Warning: Voice is off.", "Error: No brain could answer."]
    r.state.notify_warnings = False
    await r.channel.notifier.handle(Notice(level="error", text="Again."))
    assert len(r.transport.sent) == 2


async def test_nothing_is_sent_before_pairing() -> None:
    r = rig(paired=False)
    await r.channel.notifier.handle(Notice(level="error", text="x"))
    await r.channel.notifier.handle(AutomationFinished(id="a", name="n", status="ok", reply="r"))
    await r.channel.notifier.handle(request())
    assert r.transport.sent == [] and r.transport.buttons == []


async def test_requests_follow_their_switch() -> None:
    r = rig()
    r.state.notify_approvals = False
    await r.channel.notifier.handle(request())
    assert r.transport.buttons == [] and r.transport.sent == []


def test_button_data_round_trips() -> None:
    assert parse_data(button_data("abc123", "allow")) == ("abc123", "allow")
    assert parse_data(button_data("abc123", "deny")) == ("abc123", "deny")
    assert parse_data("gate:abc:maybe") is None and parse_data("other:abc:allow") is None


async def test_an_allowed_tool_is_approved_from_the_phone() -> None:
    r = rig()
    req = request()
    r.host.pending[req.id] = req
    await r.channel.notifier.handle(req)
    chat, text, buttons = r.transport.buttons[0]
    assert chat == CHAT and "https://example.org" in text and "open_url" in text
    assert [(b.label, b.kind) for b in buttons] == [("Yes", "yes"), ("Not now", "no")]
    async with r.host.bus.subscribe({GateDecision.TYPE}) as decisions:
        await r.channel.approvals.press(press(buttons[0].data))
        decision = await decisions.__anext__()
    assert decision == GateDecision(id=req.id, decision="allow", ts=decision.ts)
    assert r.transport.acks[-1][1] is not None and "Approved from the phone" in str(r.transport.acks[-1][1])
    await r.channel.notifier.handle(GateResolved(id=req.id, decision="allow"))
    assert r.transport.edits[-1][2].endswith("Approved from the phone; it ran.")


async def test_shell_is_approved_only_at_the_mac() -> None:
    r = rig()
    r.state.phone_tools = ["shell", "open_url"]  # even if the file says so
    req = request(tool="shell", detail="rm -rf ~/Downloads/old")
    r.host.pending[req.id] = req
    await r.channel.notifier.handle(req)
    assert r.transport.buttons == []
    (_, text), = r.transport.sent
    assert "rm -rf ~/Downloads/old" in text and "Approve this at the Mac: shell is never approved from the phone." in text
    async with r.host.bus.subscribe({GateDecision.TYPE}) as decisions:
        await r.channel.approvals.press(press(button_data(req.id, "allow")))
        await nothing_on(decisions)
    assert "at the Mac" in str(r.transport.acks[-1][1])
    await r.channel.notifier.handle(GateResolved(id=req.id, decision="deny"))
    assert r.transport.edits[-1][2].endswith("Declined; it did not run.")


async def test_a_tool_left_off_the_phone_list_asks_for_the_mac() -> None:
    r = rig()
    r.state.phone_tools = ["remember"]
    req = request()
    await r.channel.notifier.handle(req)
    assert r.transport.buttons == [] and "not one of the tools the phone may approve" in r.transport.texts()[0]


async def test_a_detail_too_long_to_show_in_full_asks_for_the_mac() -> None:
    r = rig()
    await r.channel.notifier.handle(request(detail="x" * (DETAIL_ROOM + 1)))
    assert r.transport.buttons == [] and "too long to show here in full" in r.transport.texts()[0]


async def test_a_stale_button_does_nothing() -> None:
    r = rig()
    req = request()
    r.host.pending[req.id] = req
    await r.channel.notifier.handle(req)
    data = r.transport.buttons[0][2][0].data
    del r.host.pending[req.id]  # answered at the Mac meanwhile, or timed out
    async with r.host.bus.subscribe({GateDecision.TYPE}) as decisions:
        await r.channel.approvals.press(press(data))
        await nothing_on(decisions)
    assert r.transport.acks == [("i1", GONE)]


async def test_a_button_from_another_chat_is_refused_and_audited() -> None:
    r = rig()
    req = request()
    r.host.pending[req.id] = req
    await r.channel.notifier.handle(req)
    data = r.transport.buttons[0][2][0].data
    async with r.host.bus.subscribe({GateDecision.TYPE}) as decisions:
        await r.channel.approvals.press(press(data, user=STRANGER))
        await r.channel.approvals.press(press(data, direct=False, press_id="i2"))
        await nothing_on(decisions)
    assert r.transport.acks == [("i1", None), ("i2", None)]
    assert [a.result for a in r.host.audits] == ["button pressed by someone other than the paired owner"] * 2


@pytest.mark.parametrize(("outcome", "words"), [("deny", "Declined; it did not run."), ("timeout", "Nobody answered in time")])
async def test_the_message_says_how_a_request_ended_at_the_mac(outcome: str, words: str) -> None:
    r = rig()
    req = request()
    await r.channel.notifier.handle(req)
    await r.channel.notifier.handle(GateResolved(id=req.id, decision=outcome))  # type: ignore[arg-type]
    assert words in r.transport.edits[-1][2]
