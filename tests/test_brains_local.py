"""The host's local brain on a mocked OpenAI-compatible server: streaming, history, keys,
errors, interrupts, and tools (sent in the standard shape, `tool_calls` read back, a
malformed call answered with an error and never run, a server that refuses tools)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from vision.brains.engine import LocalEngine
from vision.brains.local import LocalBrain
from vision.brains.local_rules import NO_TOOLS, rules
from vision.brains.local_server import ServerBackend, probe
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import BrainError, TextDelta, ToolSpec, TurnDone
from vision.testing.fakes import FakeMemory, FakeToolHost


def sse(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def delta(text: str, finish: str | None = None) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


def call_delta(index: int, name: str, arguments: str, call_id: str = "") -> dict[str, Any]:
    part = {"index": index, "id": call_id, "function": {"name": name, "arguments": arguments}}
    return {"choices": [{"index": 0, "delta": {"tool_calls": [part]}, "finish_reason": None}]}


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

    def body(self, index: int) -> dict[str, Any]:
        return dict(json.loads(self.requests[index].content))


def engine_for(config: Config, server: Server) -> LocalEngine:
    config.brain.local_backend = "openai"
    transport = httpx.MockTransport(server)
    return LocalEngine(
        config, Bus(), factory=lambda cfg, bus, backend, repo: ServerBackend(cfg, repo, transport=transport)
    )


async def start(config: Config, server: Server, tools: FakeToolHost | None = None) -> LocalBrain:
    brain = LocalBrain(config, FakeMemory("PERSONA"), engine_for(config, server), tools)
    await brain.start()
    return brain


def ok(*chunks: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=sse(*chunks), headers={"content-type": "text/event-stream"})


def remember_host() -> FakeToolHost:
    async def remember(args: dict[str, Any]) -> str:
        return f"Noted: {args['text']}"

    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    return FakeToolHost({"remember": (ToolSpec("remember", "Save a note.", schema), remember)})


async def test_streams_reply_with_usage_and_keeps_history(config: Config) -> None:
    usage = {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 4}}
    server = Server([ok(delta("Hel"), delta("lo.", "stop"), usage), ok(delta("Again.", "stop"))])
    brain = await start(config, server)
    events = [e async for e in brain.send("Hi")]
    assert events == [TextDelta("Hel"), TextDelta("lo."), TurnDone(config.brain.local_model, 30, 4, "end_turn")]
    body = server.body(0)
    assert body["model"] == config.brain.local_model and body["stream"] is True
    assert body["messages"] == [
        {"role": "system", "content": f"PERSONA\n\n{NO_TOOLS}"},
        {"role": "user", "content": "Hi"},
    ]
    assert "tools" not in body
    assert str(server.requests[0].url) == config.brain.local_base_url + "/chat/completions"

    _ = [e async for e in brain.send("More")]
    second = server.body(1)["messages"]
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


async def test_a_tool_call_goes_through_the_host_and_back(config: Config) -> None:
    server = Server(
        [
            ok(call_delta(0, "remember", '{"text": "milk"', "c1"), call_delta(0, "", "}")),
            ok(delta("Saved.", "stop")),
        ]
    )
    host = remember_host()
    brain = await start(config, server, host)
    events = [e async for e in brain.send("Remember milk")]
    assert host.calls == [("remember", {"text": "milk"})]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Saved."
    first = server.body(0)
    assert first["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Save a note.",
                "parameters": host.specs()[0].input_schema,
            },
        }
    ]
    assert first["messages"][0]["content"] == f"PERSONA\n\n{rules(tools=True, offline=False)}"
    second = server.body(1)["messages"]
    assert second[-2]["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "remember", "arguments": '{"text": "milk"}'}}
    ]
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "name": "remember", "content": "Noted: milk"}


async def test_a_malformed_call_is_answered_and_never_run(config: Config) -> None:
    server = Server(
        [
            ok(call_delta(0, "remember", '{"text": milk}', "c1")),
            ok(call_delta(0, "remember", "{}", "c2")),
            ok(call_delta(0, "forget", '{"text": "x"}', "c3")),
            ok(delta("never")),
        ]
    )
    host = remember_host()
    brain = await start(config, server, host)
    events = [e async for e in brain.send("Remember milk")]
    assert host.calls == []
    said = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert "could not write a correct tool call" in said and isinstance(events[-1], TurnDone)
    scolding = server.body(1)["messages"][-1]
    assert scolding["role"] == "user" and "not valid JSON" in scolding["content"]
    assert "remember needs text" in server.body(2)["messages"][-1]["content"]
    assert len(server.requests) == 3  # the third bad call ends the turn


async def test_a_server_that_refuses_tools_is_asked_again_without(config: Config) -> None:
    server = Server([httpx.Response(400), ok(delta("Plain answer.", "stop")), ok(delta("Again.", "stop"))])
    brain = await start(config, server, remember_host())
    events = [e async for e in brain.send("Hi")]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Plain answer."
    assert "tools" in server.body(0) and "tools" not in server.body(1)
    assert brain.engine.known_tools() is False
    _ = [e async for e in brain.send("Hi again")]
    assert "tools" not in server.body(2)  # talk-only from now on
    assert NO_TOOLS in server.body(2)["messages"][0]["content"]


async def test_probe_lists_the_servers_models() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "qwen3:8b"}, {"id": "llama3.2"}]})

    found = await probe("http://127.0.0.1:1234/v1", None, transport=httpx.MockTransport(answer))
    assert found.ok and found.models == ["qwen3:8b", "llama3.2"]

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    gone = await probe("http://127.0.0.1:1234/v1", None, transport=httpx.MockTransport(down))
    assert not gone.ok and "Is the server running?" in gone.message
