import asyncio

from vision.core.bus import Bus
from vision.core.events import InputText, Notice, VoiceLevel


async def test_subscriber_gets_only_its_types_in_order() -> None:
    bus = Bus()
    sub = bus.subscribe({"notice"})
    bus.publish(Notice(level="info", text="one"))
    bus.publish(InputText(text="ignored"))
    bus.publish(Notice(level="warn", text="two"))
    first = await asyncio.wait_for(sub.get(), 1)
    second = await asyncio.wait_for(sub.get(), 1)
    assert [first.text, second.text] == ["one", "two"]  # type: ignore[attr-defined]


async def test_subscribe_all_and_fan_out() -> None:
    bus = Bus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish(InputText(text="hi"))
    assert (await a.get()).TYPE == (await b.get()).TYPE == "input.text"


async def test_closed_subscription_receives_nothing() -> None:
    bus = Bus()
    async with bus.subscribe() as sub:
        pass
    bus.publish(InputText(text="hi"))
    assert sub._queue.empty()


async def test_iteration() -> None:
    bus = Bus()
    sub = bus.subscribe({"input.text"})
    for i in range(3):
        bus.publish(InputText(text=str(i)))
    got = []
    async for event in sub:
        got.append(event.text)  # type: ignore[attr-defined]
        if len(got) == 3:
            break
    assert got == ["0", "1", "2"]


async def test_slow_subscriber_drops_oldest() -> None:
    bus = Bus()
    sub = bus.subscribe(maxsize=2)
    for level in (0.1, 0.2, 0.3):
        bus.publish(VoiceLevel(level=level))
    assert sub.dropped == 1
    assert [(await sub.get()).level for _ in range(2)] == [0.2, 0.3]  # type: ignore[attr-defined]
