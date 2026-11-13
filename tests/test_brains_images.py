"""What each brain is sent when the owner's message carries images."""

from __future__ import annotations

import base64

import pytest
from test_brains_claude import StubStream, collect, make_brain, text_message

from vision.brains import claude as claude_mod
from vision.brains import local_rules
from vision.brains.engine import LocalEngine
from vision.brains.local import SEES_IMAGES, LocalBrain
from vision.brains.router import Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Picture, TextDelta, TurnDone
from vision.testing.fakes import FakeBrain, FakeBudget, FakeMemory, FakeToolHost


def picture(n: int = 1, kind: str = "image/png") -> Picture:
    return Picture(f"{n:032x}", kind, 10, 8, f"pixels-{n}".encode())


def image_blocks(message: dict) -> list[dict]:
    content = message["content"]
    return [] if isinstance(content, str) else [b for b in content if b["type"] == "image"]


# ---------------------------------------------------------------- Claude


async def test_images_go_first_in_the_users_message(config: Config) -> None:
    brain, client, _, _ = await make_brain(config, [StubStream(["A red square."], text_message("A red square."))])
    await collect(brain, "What is this?", images=[picture(1), picture(2, "image/jpeg")])
    (sent,) = client.requests[0]["messages"]
    assert sent["role"] == "user"
    assert sent["content"] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"pixels-1").decode()}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"pixels-2").decode()}},
        {"type": "text", "text": "What is this?"},
    ]


async def test_a_text_turn_is_sent_as_before(config: Config) -> None:
    brain, client, _, _ = await make_brain(config, [StubStream(["Hi."], text_message("Hi."))])
    await collect(brain, "Hello")
    assert client.requests[0]["messages"] == [{"role": "user", "content": "Hello"}]


async def test_earlier_images_stay_until_a_trim(config: Config) -> None:
    streams = [StubStream([f"r{i}"], text_message(f"r{i}")) for i in range(3)]
    brain, client, _, _ = await make_brain(config, streams)
    await collect(brain, "look", images=[picture(1)])
    await collect(brain, "and now?")
    await collect(brain, "still there?")
    history = client.requests[2]["messages"]
    assert len(image_blocks(history[0])) == 1  # unchanged, so the cached prefix holds


async def test_too_many_carried_images_trims_and_drops_them(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(claude_mod, "MAX_CARRIED_IMAGES", 3)
    streams = [StubStream([f"r{i}"], text_message(f"r{i}")) for i in range(3)]
    brain, client, _, _ = await make_brain(config, streams)
    await collect(brain, "first", images=[picture(1), picture(2)])
    await collect(brain, "second")
    await collect(brain, "third", images=[picture(3), picture(4)])
    messages = client.requests[2]["messages"]
    assert image_blocks(messages[0]) == []
    assert claude_mod.DROPPED_IMAGE in messages[0]["content"]
    assert {"type": "text", "text": "first"} in messages[0]["content"]
    assert len(image_blocks(messages[-1])) == 2
    for m in messages[:-1]:
        if m["role"] == "assistant":
            assert all(b["type"] != "thinking" for b in m["content"])


async def test_the_history_trim_drops_images_too(config: Config) -> None:
    config.brain.history_turns = 4  # type: ignore[attr-defined]
    streams = [StubStream([f"r{i}"], text_message(f"r{i}")) for i in range(5)]
    brain, client, _, _ = await make_brain(config, streams)
    for i in range(5):
        await collect(brain, f"q{i}", images=[picture(i + 1)])
    last = client.requests[-1]["messages"]
    users = [m for m in last if m["role"] == "user"]
    assert [len(image_blocks(m)) for m in users] == [0, 0, 1]


async def test_image_tokens_are_counted_in_the_budget(config: Config) -> None:
    usage = {"input_tokens": 1_600, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    brain, _, budget, _ = await make_brain(config, [StubStream(["ok"], text_message("ok", usage=usage))])
    events = await collect(brain, "what is it", images=[picture(1)])
    assert events[-1].input_tokens == 1_600
    assert budget.spent_usd == pytest.approx((1_600 * 0.10 + 10 * 0.50) / 1e6)


# ---------------------------------------------------------------- local


class NoEngine(LocalEngine):
    """An engine that must never be asked to generate."""

    async def generate(self, *a: object, **kw: object):  # type: ignore[override]
        raise AssertionError("a local model was sent a message with images")


@pytest.mark.parametrize("offline", [True, False])
async def test_the_local_model_says_it_cannot_see_and_is_never_sent_images(config: Config, offline: bool) -> None:
    config.brain.offline = offline
    brain = LocalBrain(config, FakeMemory(), NoEngine(config, Bus()), FakeToolHost())
    events = [e async for e in brain.send("what is this?", images=[picture(1), picture(2)])]
    line = local_rules.cannot_see(2, offline=offline)
    assert events == [TextDelta(line), TurnDone(config.brain.local_model, 0, 0, "end_turn")]
    assert "can't see images" in line and "the 2 images you sent" in line
    assert ("offline mode off" in line) is offline
    assert brain._history[-1][1] == {"role": "assistant", "content": line}
    assert SEES_IMAGES is False


async def test_offline_mode_routes_images_to_the_local_brain(config: Config) -> None:
    config.brain.offline = True
    claude, local = FakeBrain(["claude"], delay=0), FakeBrain(["local"], delay=0, name="local")
    router = Router(config, Bus(), claude, local, FakeBudget())  # type: ignore[arg-type]
    [e async for e in router.send("hi", images=[picture(1)])]
    assert claude.sent == [] and local.images == [(picture(1),)]


def test_the_catalog_records_which_models_have_a_vision_encoder() -> None:
    from vision.brains.catalog import load_catalog

    seeing = {m.id for m in load_catalog().models if m.images}
    assert "mlx-community/Qwen3-4B-Instruct-2507-4bit" not in seeing
    assert "mlx-community/gemma-4-31b-it-4bit" in seeing
    assert len(seeing) == 6


def test_the_hand_off_says_images_stay_behind() -> None:
    from vision.jobs.tools import HAND_OFF

    assert "Images the owner sent never go along" in HAND_OFF
    assert "write into the brief everything that matters in it" in HAND_OFF
