"""The local brain against a mocked OpenAI-compatible server."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from vision.brains.local import LocalBrain
from vision.brains.local_rules import NO_TOOLS, with_rules
from vision.core.config import Config
from vision.core.interfaces import BrainError, TextDelta, TurnDone
from vision.testing.fakes import FakeMemory


def sse(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def delta(text: str, finish: str | None = None) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


class Server:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def start(config: Config, server: Server) -> LocalBrain:
    brain = LocalBrain(config, FakeMemory("PERSONA"), transport=httpx.MockTransport(server))
    await brain.start()
    return brain


def ok(*chunks: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=sse(*chunks), headers={"content-type": "text/event-stream"})


async def test_streams_reply_with_usage_and_keeps_history(config: Config) -> None:
    usage = {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 4}}
    server = Server([ok(delta("Hel"), delta("lo.", "stop"), usage), ok(delta("Again.", "stop"))])
    brain = await start(config, server)
    events = [e async for e in brain.send("Hi")]
    assert events == [TextDelta("Hel"), TextDelta("lo."), TurnDone(config.brain.local_model, 30, 4, "end_turn")]
    body = json.loads(server.requests[0].content)
    assert body["model"] == config.brain.local_model and body["stream"] is True
    assert NO_TOOLS in with_rules("PERSONA")
    assert body["messages"] == [{"role": "system", "content": with_rules("PERSONA")}, {"role": "user", "content": "Hi"}]
    assert "tools" not in body
    assert str(server.requests[0].url) == config.brain.local_base_url + "/chat/completions"

    _ = [e async for e in brain.send("More")]
    second = json.loads(server.requests[1].content)["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == "Hello."
    await brain.close()


async def test_optional_key_is_sent_from_named_env_var(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    config.brain.local_api_key_env = "TEST_LOCAL_KEY"  # type: ignore[attr-defined]
    monkeypatch.setenv("TEST_LOCAL_KEY", "abc")
    server = Server([ok(delta("x", "stop"))])
    brain = await start(config, server)
    _ = [e async for e in brain.send("Hi")]
    assert server.requests[0].headers["authorization"] == "Bearer abc"


async def test_no_key_header_by_default(config: Config) -> None:
    server = Server([ok(delta("x", "stop"))])
    brain = await start(config, server)
    _ = [e async for e in brain.send("Hi")]
    assert "authorization" not in server.requests[0].headers


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(404), "bad_request"),
        (httpx.Response(401), "auth"),
        (httpx.Response(429), "rate_limit"),
        (httpx.Response(500), "unavailable"),
        (httpx.ConnectError("refused"), "unavailable"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.Response(200, content=b"data: {not json\n\n"), "internal"),
    ],
)
async def test_errors(config: Config, response: Any, kind: str) -> None:
    brain = await start(config, Server([response]))
    [event] = [e async for e in brain.send("Hi")]
    assert isinstance(event, BrainError) and event.kind == kind
    assert brain._history == []


async def test_interrupt_keeps_partial_reply(config: Config) -> None:
    server = Server([ok(delta("One "), delta("two "), delta("three", "stop"))])
    brain = await start(config, server)
    events = []
    async for event in brain.send("Count"):
        events.append(event)
        if len(events) == 1:
            await brain.interrupt()
    assert events[0] == TextDelta("One ") and events[-1].stop_reason == "interrupted"
    assert brain._history[0][1]["content"].startswith("One")
