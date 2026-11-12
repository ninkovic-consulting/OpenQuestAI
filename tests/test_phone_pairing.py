"""Pairing: only the owner is served; everyone else gets one fixed line and an audit row."""

from __future__ import annotations

from phone_fakes import CHAT, OWNER, STRANGER, dm, rig, settle, voice_note

from vision.core.events import Notice
from vision.remote import words
from vision.remote.pairing import CODE_TTL_S, MAX_TRIES, Pairing, looks_like_code, normalize


def test_codes_read_loosely_but_only_six_digits_count() -> None:
    assert normalize(" 482 913 ") == normalize("482-913") == normalize("pair 482913") == "482913"
    assert looks_like_code("482 913")
    assert not looks_like_code("hello") and not looks_like_code("12345") and not looks_like_code("1234567")


def test_a_code_expires_and_is_used_up() -> None:
    now = [0.0]
    pairing = Pairing(clock=lambda: now[0])
    code = pairing.issue()
    assert len(code.code) == 6 and code.expires_at == CODE_TTL_S
    assert pairing.check(code.code) == "paired"
    assert pairing.check(code.code) == "none"
    code = pairing.issue()
    now[0] = CODE_TTL_S + 1
    assert pairing.current() is None
    assert pairing.check(code.code) == "none"


def test_wrong_tries_void_the_code() -> None:
    pairing = Pairing(clock=lambda: 0.0)
    code = pairing.issue()
    wrong = "000000" if code.code != "000000" else "111111"
    for _ in range(MAX_TRIES):
        assert pairing.check(wrong) == "wrong"
    assert pairing.check(code.code) == "none"


async def test_the_right_code_pairs_that_chat() -> None:
    r = rig(paired=False)
    code = r.pairing.issue()
    async with r.host.bus.subscribe({Notice.TYPE}) as notices:
        await r.channel.on_message(dm(f"{code.code[:3]} {code.code[3:]}", user=OWNER))
        notice = await notices.__anext__()
    assert r.state.owner_id == OWNER and r.state.chat_id == CHAT and r.state.paired_at > 0
    assert r.saves and r.saves[-1].owner_id == OWNER
    assert r.transport.texts()[-1].startswith("Paired.")
    assert isinstance(notice, Notice) and "paired" in notice.text
    assert r.host.turns == [] and r.host.audits == []


async def test_a_wrong_code_runs_nothing_and_is_audited() -> None:
    r = rig(paired=False)
    code = r.pairing.issue()
    wrong = "999999" if code.code != "999999" else "888888"
    await r.channel.on_message(dm(wrong, user=STRANGER))
    assert not r.state.paired
    assert r.transport.texts() == [words.PRIVATE]
    audit = r.host.audits[-1]
    assert audit.tool == "phone" and audit.decision == "deny" and audit.result == "pairing code wrong"
    assert audit.args == {"user_id": STRANGER, "user_name": "Someone", "kind": "code"}
    assert wrong not in str(audit)


async def test_an_expired_code_does_not_pair() -> None:
    clock = [1000.0]
    r = rig(paired=False, clock=clock)
    code = r.pairing.issue()
    clock[0] += CODE_TTL_S + 1
    await r.channel.on_message(dm(code.code))
    assert not r.state.paired
    assert r.host.audits[-1].result == "pairing code expired"
    assert r.transport.texts() == [words.PRIVATE]


async def test_before_pairing_messages_reveal_nothing() -> None:
    r = rig(paired=False)
    await r.channel.on_message(dm("status"))
    await r.channel.on_message(dm("what is my dentist appointment?"))
    await settle()
    assert r.host.turns == []
    assert r.transport.texts() == [words.PRIVATE]  # once a minute at most
    assert [a.result for a in r.host.audits] == ["not paired yet", "not paired yet"]


async def test_a_second_chat_is_refused_after_pairing() -> None:
    clock = [1000.0]
    r = rig(paired=True, clock=clock)
    await r.channel.on_message(dm("status", user=STRANGER))
    await r.channel.on_message(dm("123456", user=STRANGER))
    await r.channel.on_message(dm("", user=STRANGER, attachments=(voice_note(),)))
    clock[0] += 61
    await r.channel.on_message(dm("hello", user=STRANGER))
    await settle()
    assert r.host.turns == [] and r.ears.heard == []
    assert r.transport.texts() == [words.PRIVATE, words.PRIVATE]
    assert [a.result for a in r.host.audits] == ["not the paired owner"] * 4
    assert [a.args["kind"] for a in r.host.audits] == ["text", "text", "voice", "text"]
    assert r.state.owner_id == OWNER


async def test_server_messages_are_ignored_entirely() -> None:
    r = rig(paired=False)
    code = r.pairing.issue()
    await r.channel.on_message(dm(code.code, direct=False))
    await r.channel.on_message(dm("hello", user=STRANGER, direct=False))
    assert not r.state.paired and r.transport.sent == [] and r.host.audits == []
