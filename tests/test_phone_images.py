"""Images from the paired phone: fetched, checked, kept and sent with the message's turn."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from image_fixtures import SECRET, jpeg_with_location, png
from phone_fakes import CHAT, Rig, dm, rig
from test_phone_channel import until

from vision.attachments.clean import TOO_BIG
from vision.core.events import MAX_IMAGES
from vision.remote import words
from vision.remote.transport import Attachment


def attachment(n: int, data: bytes, rig_: Rig, *, name: str = "photo.jpg", size: int | None = None) -> Attachment:
    url = f"cdn://img{n}"
    rig_.transport.files[url] = data
    return Attachment(url, name, "image/jpeg", len(data) if size is None else size, voice=False)


@pytest.fixture
async def running() -> AsyncIterator[Rig]:
    r = rig()
    task = asyncio.create_task(r.channel.run())
    yield r
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_text_with_an_image_is_one_turn(running: Rig) -> None:
    r = running
    photo = attachment(1, jpeg_with_location(), r)
    await r.channel.on_message(dm("What is in this?", attachments=(photo,)))
    await until(lambda: r.transport.sent)
    assert r.host.turns == [("What is in this?", False)]
    (kept,) = r.host.pictures[0]
    assert kept.media_type == "image/jpeg" and SECRET not in kept.data
    assert r.transport.sent == [(CHAT, "Echo: What is in this?")]


async def test_an_image_alone_runs_a_turn(running: Rig) -> None:
    r = running
    await r.channel.on_message(dm("", attachments=(attachment(1, png(5, 5), r, name="a.png"),)))
    await until(lambda: r.transport.sent)
    assert r.host.turns == [("", False)] and len(r.host.pictures[0]) == 1


async def test_several_images_go_up_to_the_cap(running: Rig) -> None:
    r = running
    files = tuple(attachment(i, png(3, 3), r, name=f"{i}.png") for i in range(MAX_IMAGES + 2))
    await r.channel.on_message(dm("all of these", attachments=files))
    await until(lambda: len(r.transport.sent) == 2)
    assert len(r.host.pictures[0]) == MAX_IMAGES
    assert r.transport.texts()[0] == f"Only the first {MAX_IMAGES} images of a message are read; 2 more were left out."


async def test_a_refused_attachment_is_named_and_the_rest_still_go(running: Rig) -> None:
    r = running
    good = attachment(1, png(3, 3), r, name="ok.png")
    text_file = attachment(2, b"plain words", r, name="notes.png")
    huge = attachment(3, b"x", r, name="big.jpg", size=20 * 1024 * 1024)
    await r.channel.on_message(dm("", attachments=(good, text_file, huge)))
    await until(lambda: len(r.transport.sent) == 2)
    assert r.transport.texts()[0] == (
        "I couldn't use 2 attachments: That file is not a PNG, JPEG, GIF or WebP image. " + TOO_BIG
    )
    assert len(r.host.pictures[0]) == 1


async def test_nothing_usable_and_no_words_runs_nothing(running: Rig) -> None:
    r = running
    await r.channel.on_message(dm("", attachments=(attachment(1, b"%PDF-1.4", r, name="x.pdf"),)))
    await asyncio.sleep(0.05)
    assert r.transport.texts() == [words.ONLY_TEXT] and r.host.turns == []


async def test_a_command_with_an_image_is_a_message(running: Rig) -> None:
    r = running
    await r.channel.on_message(dm("status", attachments=(attachment(1, png(3, 3), r, name="s.png"),)))
    await until(lambda: r.transport.sent)
    assert r.host.turns == [("status", False)]


async def test_images_of_messages_that_waited_go_together_in_order(running: Rig) -> None:
    r = running
    r.host.is_busy = True
    await r.channel.on_message(dm("first", attachments=(attachment(1, png(4, 4), r, name="a.png"),)))
    await r.channel.on_message(dm("", attachments=(attachment(2, png(6, 6), r, name="b.png"),)))
    await r.channel.on_message(dm("and why"))
    r.host.is_busy = False
    await until(lambda: r.transport.sent)
    assert r.host.turns == [("first\n\nand why", False)]
    assert [p.width for p in r.host.pictures[0]] == [4, 6]
