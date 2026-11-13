"""A WebSocket client drives one full turn on a daemon running the fake brain."""

import asyncio
import json
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect

from vision.app import Daemon
from vision.core.events import Hello, InputInterrupt, InputText
from vision.testing.fakes import FakeBrain, FakeMemory


async def collect_turn(ws: ClientConnection, timeout: float = 10) -> list[dict[str, Any]]:
    """Receive events until the state returns to idle after a reply."""
    events: list[dict[str, Any]] = []
    replied = False
    async with asyncio.timeout(timeout):
        while True:
            event = json.loads(await ws.recv())
            events.append(event)
            replied = replied or event["type"] == "vision.reply"
            if replied and event["type"] == "state.changed" and event["data"]["state"] == "idle":
                return events


def compress(events: list[dict[str, Any]]) -> list[str]:
    """Event names in order, with runs of deltas collapsed and states spelled out.

    `room.state` follows the conversation state asynchronously, so it is left out.
    """
    out: list[str] = []
    for e in events:
        name = e["type"]
        if name == "room.state":
            continue
        if name == "state.changed":
            name = f"state:{e['data']['state']}"
        if name == "vision.delta" and out and out[-1] == "vision.delta":
            continue
        out.append(name)
    return out


async def open_socket(daemon: Daemon) -> ClientConnection:
    ws = await connect(f"ws://127.0.0.1:{daemon.port}/ws")
    await ws.send(Hello(token=daemon.token).to_json())
    return ws


async def test_text_turn_event_sequence_and_log(fake_daemon: Daemon) -> None:
    daemon = fake_daemon
    ws = await open_socket(daemon)
    try:
        await ws.send(InputText(text="Hello there").to_json())
        events = await collect_turn(ws)
    finally:
        await ws.close()

    assert compress(events) == [
        "user.utterance",
        "state:thinking",
        "vision.delta",
        "state:speaking",
        "vision.delta",
        "vision.reply",
        "state:idle",
    ]
    assert events[0]["data"] == {"text": "Hello there", "source": "text", "images": []}
    assert all(e["data"]["brain"] == "fake" for e in events if e["type"] == "state.changed")
    deltas = "".join(e["data"]["text"] for e in events if e["type"] == "vision.delta")
    reply = next(e for e in events if e["type"] == "vision.reply")["data"]
    assert reply["text"] == deltas
    assert deltas.startswith("I am running on the fake brain.")

    memory = daemon.components.memory
    assert isinstance(memory, FakeMemory)
    [turn] = memory.turns
    assert (turn.turn_id, turn.status, turn.user_text, turn.reply) == (
        reply["turn_id"],
        "ok",
        "Hello there",
        deltas,
    )
    assert turn.brain == "fake" and turn.model == "fake-1" and turn.output_tokens > 0

    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{daemon.port}",
        headers={"Authorization": f"Bearer {daemon.token}"},
    ) as client:
        history = (await client.get("/api/history", params={"limit": 5})).json()
    assert [t["turn_id"] for t in history["turns"]] == [reply["turn_id"]]


async def test_interrupt_over_socket(fake_daemon: Daemon) -> None:
    daemon = fake_daemon
    brain = daemon.components.brain
    assert isinstance(brain, FakeBrain)
    brain.delay = 0.2  # slow enough to interrupt mid-reply
    ws = await open_socket(daemon)
    try:
        await ws.send(InputText(text="Tell me a long story").to_json())
        async with asyncio.timeout(5):
            while json.loads(await ws.recv())["type"] != "vision.delta":
                pass
        await ws.send(InputInterrupt().to_json())
        events = await collect_turn(ws)
    finally:
        await ws.close()
    assert compress(events)[-2:] == ["vision.reply", "state:idle"]
    memory = daemon.components.memory
    assert isinstance(memory, FakeMemory)
    [turn] = memory.turns
    assert turn.status == "interrupted"
    assert brain.interrupts == 1
    assert len(turn.reply.split()) < len(brain._replies[0].split())
