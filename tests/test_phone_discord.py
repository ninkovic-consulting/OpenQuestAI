"""The Discord transport against a local fake of Discord's HTTP API, CDN and Gateway."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import uvicorn
from conftest import free_port

from vision.remote.discord.gateway import Gateway
from vision.remote.discord.markdown import MAX_CONTENT, escape, escaped_length
from vision.remote.discord.rest import DiscordRest, route_key
from vision.remote.discord.transport import DiscordTransport
from vision.remote.text import split_text
from vision.remote.transport import Attachment, Handlers, Incoming, Press, TokenRefused, Unreachable
from vision.testing.fake_discord import API, FakeDiscord

TOKEN = "fake-bot-token-for-tests-1.abcdef.fake-bot-token-for-tests-only-1"


@contextlib.asynccontextmanager
async def serve(fake: FakeDiscord) -> AsyncIterator[FakeDiscord]:
    port = free_port()
    fake.base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(fake.app(), host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    try:
        yield fake
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


@pytest.fixture
async def discord() -> AsyncIterator[FakeDiscord]:
    async with serve(FakeDiscord(token=TOKEN)) as fake:
        yield fake


def transport(fake: FakeDiscord, token: str = TOKEN) -> DiscordTransport:
    return DiscordTransport(token, base=fake.base_url + API)


async def until(predicate: Callable[[], object], seconds: float = 5.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


async def no_wait(seconds: float) -> None:
    return None


class Listener:
    def __init__(self) -> None:
        self.messages: list[Incoming] = []
        self.presses: list[Press] = []
        self.states: list[bool] = []

    def handlers(self) -> Handlers:
        async def message(m: Incoming) -> None:
            self.messages.append(m)

        async def press(p: Press) -> None:
            self.presses.append(p)

        return Handlers(message=message, press=press, online=self.states.append)


@contextlib.asynccontextmanager
async def listening(t: DiscordTransport) -> AsyncIterator[tuple[Listener, asyncio.Task[None]]]:
    who = Listener()
    task = asyncio.create_task(t.listen(who.handlers()))
    try:
        await until(lambda: who.states and who.states[-1])
        yield who, task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await t.close()


# ---------------------------------------------------------------- text


def test_markdown_is_escaped_but_links_are_left_whole() -> None:
    assert escape("*bold* _it_ ~x~ `c` |s| > q # h - l [a](b) <@1>") == (
        r"\*bold\* \_it\_ \~x\~ \`c\` \|s\| \> q \# h \- l \[a\]\(b\) \<@1\>"
    )
    assert escape(r"a\b") == r"a\\b"
    assert escape("see https://example.org/a_b*c (here)") == r"see https://example.org/a_b*c \(here\)"


def test_long_text_splits_at_natural_places_within_the_limit() -> None:
    sentence = "This is one sentence with *stars* in it. "
    text = (sentence * 40).strip() + "\n\n" + (sentence * 40).strip()
    pieces = split_text(text, MAX_CONTENT, escaped_length)
    assert len(pieces) >= 2
    assert all(escaped_length(p) <= MAX_CONTENT for p in pieces)
    assert all(p.endswith(".") for p in pieces)
    assert " ".join(pieces).replace("\n\n", " ").split() == text.split()


def test_a_word_longer_than_a_message_is_cut_hard() -> None:
    pieces = split_text("x" * 4500, MAX_CONTENT)
    assert [len(p) for p in pieces] == [2000, 2000, 500]


def test_rate_limit_routes_ignore_message_ids() -> None:
    assert route_key("PATCH", "/channels/7/messages/123") == route_key("PATCH", "/channels/7/messages/456")
    assert route_key("POST", "/interactions/9/tok/callback") == "POST /interactions/:id/callback"


# ---------------------------------------------------------------- the API


async def test_identify_and_a_refused_token(discord: FakeDiscord) -> None:
    t = transport(discord)
    me = await t.identify()
    assert (me.id, me.name) == ("900", "Vision Bot")
    await t.close()
    bad = transport(discord, token=TOKEN[:-2] + "zz")
    with pytest.raises(TokenRefused):
        await bad.identify()
    await bad.close()


async def test_messages_are_split_escaped_and_mention_nobody(discord: FakeDiscord) -> None:
    t = transport(discord)
    await t.send("700", "@everyone look: " + ("word " * 600))
    sent = discord.sent()
    assert len(sent) == 2
    assert all(len(m["content"]) <= MAX_CONTENT for m in sent)
    assert all(m["allowed_mentions"] == {"parse": []} for m in sent)
    await t.close()


async def test_a_429_waits_and_tries_again(discord: FakeDiscord) -> None:
    discord.rate_limit_next = 2
    t = transport(discord)
    await t.send("700", "hello")
    assert [m["content"] for m in discord.sent()] == ["hello"]
    await t.close()


async def test_unreachable_is_reported_after_retries() -> None:
    async def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    rest = DiscordRest(TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)), sleep=no_wait)
    with pytest.raises(Unreachable) as caught:
        await rest.call("POST", "/channels/1/typing")
    assert TOKEN not in str(caught.value)


async def test_buttons_edits_and_acknowledgements(discord: FakeDiscord) -> None:
    from vision.remote.transport import Button

    t = transport(discord)
    message_id = await t.send_buttons("700", "Needs your yes", [Button("gate:r1:allow", "Yes", "yes"), Button("gate:r1:deny", "Not now", "no")])
    row = discord.sent()[0]["components"][0]
    assert row["type"] == 1 and [(b["style"], b["custom_id"]) for b in row["components"]] == [(3, "gate:r1:allow"), (2, "gate:r1:deny")]
    await t.edit("700", message_id, "Approved")
    assert discord.sent("edit")[0]["components"] == [] and discord.sent("edit")[0]["content"] == "Approved"
    p = Press("55", "itoken-55", "700", message_id, "111", "Owner", True, "gate:r1:allow")
    await t.acknowledge(p, "Done *now*")
    await t.acknowledge(p, None)
    first, second = discord.sent("ack")
    assert first["type"] == 7 and first["data"]["content"] == r"Done \*now\*" and first["data"]["components"] == []
    assert second == {"kind": "ack", "interaction_id": "55", "token": "itoken-55", "type": 6}
    await t.close()


async def test_voice_notes_come_from_the_cdn_without_the_token(discord: FakeDiscord) -> None:
    t = transport(discord)
    async with listening(t) as (who, _):
        await discord.dm("111", "", voice=b"OggS-fake")
        await until(lambda: who.messages)
    note = who.messages[0].attachments[0]
    assert note.voice and note.content_type == "audio/ogg"
    t = transport(discord)
    assert await t.fetch(note, 1000) == b"OggS-fake"
    with pytest.raises(Unreachable):
        await t.fetch(note, 3)
    with pytest.raises(Unreachable):
        await t.fetch(Attachment("https://elsewhere.example/x.ogg", "x.ogg", "audio/ogg", 1, True), 1000)
    await t.close()


async def test_a_voice_reply_is_a_voice_message(discord: FakeDiscord) -> None:
    t = transport(discord)
    await t.send_voice("700", b"OggS" * 10, 1.5, bytes([0, 128, 255]))
    (sent,) = discord.sent("voice")
    payload = sent["payload"]
    assert sent["voice"] == 40 and payload["flags"] == 1 << 13
    assert payload["attachments"][0]["duration_secs"] == 1.5 and payload["attachments"][0]["waveform"] == "AID/"
    await t.close()


# ---------------------------------------------------------------- the Gateway


async def test_direct_messages_and_presses_arrive_and_servers_are_marked(discord: FakeDiscord) -> None:
    async with listening(transport(discord)) as (who, _):
        await discord.dm("111", "hello there")
        await discord.dm("111", "in a server", guild_id="5")
        await discord.dm("900", "my own words", bot=True)
        await discord.press("111", "m1", "gate:r1:allow")
        await until(lambda: len(who.messages) == 2 and who.presses)
    first, second = who.messages
    assert (first.text, first.direct, first.user_id, first.chat_id) == ("hello there", True, "111", "700")
    assert second.direct is False
    assert who.presses[0].data == "gate:r1:allow" and who.presses[0].direct and who.presses[0].user_id == "111"
    assert discord.identifies == 1


async def test_a_dropped_connection_resumes_with_backoff(discord: FakeDiscord) -> None:
    async with listening(transport(discord)) as (who, _):
        await discord.drop(4000)
        await until(lambda: discord.resumes == 1 and who.states[-1], seconds=10)
        await discord.dm("111", "after the drop")
        await until(lambda: who.messages)
    assert who.states[:3] == [True, False, True]
    assert discord.identifies == 1 and who.messages[0].text == "after the drop"


async def test_a_dead_connection_is_noticed_by_its_heartbeat() -> None:
    async with serve(FakeDiscord(token=TOKEN, heartbeat_ms=60, ack_heartbeats=False)) as fake:
        async with listening(transport(fake)) as (who, _):
            await until(lambda: fake.resumes >= 1 or fake.identifies >= 2, seconds=10)
            fake.ack_heartbeats = True
            await until(lambda: who.states[-1], seconds=10)
        assert False in who.states


async def test_a_refused_token_on_the_gateway_stops_listening(discord: FakeDiscord) -> None:
    rest = DiscordRest(TOKEN, base=discord.base_url + API)

    async def ignore(event: str, data: dict[str, object]) -> None:
        return None

    gateway = Gateway(TOKEN[:-2] + "zz", rest, ignore)
    with pytest.raises(TokenRefused):
        await asyncio.wait_for(gateway.run(), 10)
    await rest.close()


async def test_back_off_grows_and_resets(discord: FakeDiscord) -> None:
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    rest = DiscordRest(TOKEN, base="http://127.0.0.1:1" + API, sleep=no_wait)  # nothing listens there

    async def ignore(event: str, data: dict[str, object]) -> None:
        return None

    gateway = Gateway(TOKEN, rest, ignore, rand=lambda: 1.0, sleep=sleep)
    task = asyncio.create_task(gateway.run())
    await until(lambda: len(delays) >= 4, seconds=30)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert delays[:4] == [1.0, 2.0, 4.0, 8.0]
    await rest.close()


async def test_the_token_never_reaches_the_log(discord: FakeDiscord, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    async with listening(transport(discord)) as (who, _):
        await discord.drop(4000)
        await until(lambda: discord.resumes == 1, seconds=10)
        await discord.dm("111", "hello")
        await until(lambda: who.messages)
    bad = transport(discord, token=TOKEN[:-2] + "zz")
    with pytest.raises(TokenRefused):
        await bad.identify()
    await bad.close()
    assert TOKEN not in caplog.text and TOKEN[:-2] not in caplog.text
