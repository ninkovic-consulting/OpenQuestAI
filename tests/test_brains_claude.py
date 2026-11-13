"""The Claude adapter against a stubbed SDK client: no network."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from vision.brains.claude import (
    NOTHING_SAID,
    OUT_OF_ROOM,
    FALLBACK_BETA,
    REFUSAL_LINE,
    ClaudeBrain,
    echo_content,
)
from vision.brains.reply_form import with_reply_form
from vision.core.config import Config
from vision.core.interfaces import BrainError, TextDelta, ToolSpec, TurnDone
from vision.testing.fakes import FakeBudget, FakeMemory, FakeToolHost

SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def message(
    content: list[dict[str, Any]],
    *,
    stop: str = "end_turn",
    model: str = "claude-haiku-5-5",
    usage: dict[str, Any] | None = None,
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": usage
            or {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 50,
            },
        }
    )


def text_message(text: str, **kw: Any) -> BetaMessage:
    return message([{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": text}], **kw)


class StubStream:
    """Plays text fragments, optionally hangs, then returns `final`."""

    def __init__(
        self,
        fragments: list[str],
        final: BetaMessage,
        *,
        hang_after: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.fragments = fragments
        self.final = final
        self.hang_after = hang_after
        self.error = error
        self.started = False
        self.closed = False

    async def __aenter__(self) -> StubStream:
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    def __aiter__(self):
        return self._events()

    async def _events(self):
        self.started = True
        yield SimpleNamespace(type="message_start")
        for i, fragment in enumerate(self.fragments):
            if self.hang_after is not None and i == self.hang_after:
                await asyncio.Event().wait()
            yield SimpleNamespace(type="text", text=fragment)

    async def get_final_message(self) -> BetaMessage:
        return self.final

    @property
    def current_message_snapshot(self) -> BetaMessage:
        assert self.started
        return self.final


class StubClient:
    def __init__(self, streams: list[StubStream]) -> None:
        self.streams = list(streams)
        self.requests: list[dict[str, Any]] = []
        self.closed = False
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs: Any) -> StubStream:
        self.requests.append(kwargs)
        return self.streams.pop(0)

    async def close(self) -> None:
        self.closed = True


async def make_brain(
    config: Config, streams: list[StubStream], tools: FakeToolHost | None = None
) -> tuple[ClaudeBrain, StubClient, FakeBudget, FakeToolHost]:
    client = StubClient(streams)
    budget = FakeBudget.from_config(config)
    host = tools or FakeToolHost()
    brain = ClaudeBrain(config, host, FakeMemory("PERSONA"), budget, client_factory=lambda key, t: client)
    brain._client = client
    return brain, client, budget, host


async def collect(brain: ClaudeBrain, text: str, **kw: Any) -> list[Any]:
    return [event async for event in brain.send(text, **kw)]


async def test_streams_text_and_records_usage(config: Config) -> None:
    brain, client, budget, _ = await make_brain(config, [StubStream(["Hel", "lo."], text_message("Hello."))])
    events = await collect(brain, "Hi")
    assert events[:2] == [TextDelta("Hel"), TextDelta("lo.")]
    assert events[2] == TurnDone("claude-haiku-5-5", 1150, 20, "end_turn")
    expected = (100 * 0.10 + 20 * 0.50 + 1000 * 0.01 + 50 * 0.125) / 1e6
    assert budget.spent_usd == pytest.approx(expected)

    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"] == {"effort": "low"}
    assert request["max_tokens"] == config.brain.max_output_tokens
    assert request["system"] == [
        {"type": "text", "text": with_reply_form("PERSONA"), "cache_control": {"type": "ephemeral"}}
    ]
    assert "Never use Markdown marks" in request["system"][0]["text"]  # replies are spoken and shown plain
    assert request["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in request and "betas" not in request and "fallbacks" not in request
    assert "tools" not in request
    assert request["messages"] == [{"role": "user", "content": "Hi"}]


async def test_heavy_uses_opus_with_refusal_fallbacks(config: Config) -> None:
    brain, client, _, _ = await make_brain(
        config, [StubStream(["Ok."], text_message("Ok.", model="claude-opus-5-5"))]
    )
    events = await collect(brain, "Think it through", heavy=True)
    assert events[-1].model == "claude-opus-5-5"
    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"] == {"effort": "high"}
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"


async def test_history_is_kept_and_system_prompt_frozen(config: Config) -> None:
    brain, client, _, _ = await make_brain(
        config, [StubStream(["A."], text_message("A.")), StubStream(["B."], text_message("B."))]
    )
    await collect(brain, "one")
    brain._memory._core = "CHANGED"  # a note was added; the cached prefix must not move
    await collect(brain, "two")
    second = client.requests[1]
    assert second["system"][0]["text"] == with_reply_form("PERSONA")
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert second["messages"][1]["content"][0]["type"] == "thinking"  # passed back unchanged


async def test_tool_round_trip_goes_through_the_tool_host(config: Config) -> None:
    async def remember(args: dict[str, Any]) -> str:
        return f"saved {args['text']}"

    host = FakeToolHost({"remember": (ToolSpec("remember", "Save a note", SCHEMA), remember)})
    tool_turn = message(
        [
            {"type": "text", "text": "Saving"},
            {"type": "tool_use", "id": "tu_1", "name": "remember", "input": {"text": "Friday"}},
        ],
        stop="tool_use",
    )
    brain, client, budget, _ = await make_brain(
        config,
        [StubStream(["Saving"], tool_turn), StubStream(["done."], text_message("done."))],
        tools=host,
    )
    events = await collect(brain, "Remember Friday")
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Saving", " done."]
    assert host.calls == [("remember", {"text": "Friday"})]
    assert events[-1].input_tokens == 2 * 1150 and events[-1].output_tokens == 40

    first, second = client.requests
    assert first["tools"] == [{"name": "remember", "description": "Save a note", "input_schema": SCHEMA}]
    assert "tool_choice" not in first
    results = second["messages"][-1]
    assert results["role"] == "user"
    assert results["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "saved Friday", "is_error": False}
    ]
    history = [m["role"] for turn in brain._history for m in turn]
    assert history == ["user", "assistant", "user", "assistant"]


async def test_interrupt_stops_promptly_and_keeps_history_consistent(config: Config) -> None:
    stream = StubStream(["Once ", "upon"], text_message("Once upon"), hang_after=1)
    brain, client, budget, _ = await make_brain(config, [stream])
    events: list[Any] = []

    async def consume() -> None:
        async for event in brain.send("Tell me a story"):
            events.append(event)
            if len(events) == 1:
                await brain.interrupt()

    await asyncio.wait_for(consume(), 1)
    assert events == [TextDelta("Once "), TurnDone("claude-haiku-5-5", 1150, 20, "interrupted")]
    assert stream.closed
    assert budget.spent_usd > 0  # what was billed is still recorded
    assert brain._history == [
        [
            {"role": "user", "content": "Tell me a story"},
            {"role": "assistant", "content": [{"type": "text", "text": "Once"}]},
        ]
    ]


async def test_consumer_stopping_early_closes_the_stream(config: Config) -> None:
    stream = StubStream(["a", "b"], text_message("ab"), hang_after=1)
    brain, _, _, _ = await make_brain(config, [stream])
    gen = brain.send("x")
    assert await gen.__anext__() == TextDelta("a")
    await gen.aclose()
    assert stream.closed
    assert brain._history[0][1]["content"][0]["text"] == "a"


async def test_refusal_is_spoken_and_partial_discarded(config: Config) -> None:
    refused = message([{"type": "text", "text": "Part"}], stop="refusal")
    brain, _, _, _ = await make_brain(config, [StubStream(["Part"], refused)])
    events = await collect(brain, "something")
    assert events[-1].stop_reason == "refusal"
    assert events[:2] == [TextDelta("Part"), TextDelta(" " + REFUSAL_LINE)]
    assert brain._history[0][1]["content"][0]["text"] == REFUSAL_LINE


async def test_a_reply_cut_at_the_limit_says_so(config: Config) -> None:
    """Thinking counts toward the limit, so a turn can end with no words; silence looks like a fault."""
    silent = message([], stop="max_tokens")
    brain, _, _, _ = await make_brain(config, [StubStream([], silent)])
    events = await collect(brain, "a long question")
    assert events[0] == TextDelta(NOTHING_SAID) and events[-1].stop_reason == "max_tokens"

    partial = message([{"type": "text", "text": "The first half"}], stop="max_tokens")
    brain, _, _, _ = await make_brain(config, [StubStream(["The first half"], partial)])
    events = await collect(brain, "a long question")
    assert events[:2] == [TextDelta("The first half"), TextDelta(" " + OUT_OF_ROOM)]


async def test_truncated_tool_call_is_not_run(config: Config) -> None:
    host = FakeToolHost()
    cut = message(
        [{"type": "tool_use", "id": "tu_1", "name": "shell", "input": {}}], stop="max_tokens"
    )
    brain, _, _, _ = await make_brain(config, [StubStream([], cut)], tools=host)
    events = await collect(brain, "run it")
    assert host.calls == [] and events[-1].stop_reason == "max_tokens"
    assert brain._history == []


async def test_no_key_is_an_auth_error(config: Config) -> None:
    brain = ClaudeBrain(config, FakeToolHost(), FakeMemory(), FakeBudget())
    await brain.start()
    assert not brain.has_key
    [event] = await collect(brain, "hi")
    assert isinstance(event, BrainError) and event.kind == "auth"


async def test_key_from_secrets_builds_client(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seen: list[tuple[str, float]] = []
    brain = ClaudeBrain(
        config, FakeToolHost(), FakeMemory(), FakeBudget(),
        client_factory=lambda key, timeout: seen.append((key, timeout)) or StubClient([]),
    )
    await brain.start()
    assert brain.has_key and seen == [("test-key", config.brain.request_timeout_s)]


REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls: type, status: int, body: Any = None) -> Exception:
    return cls("boom", response=httpx2.Response(status, request=REQ), body=body)


@pytest.mark.parametrize(
    ("exc", "kind", "retryable"),
    [
        (status_error(anthropic.EnforcedSpendLimitReachedError, 429), "credits", False),
        (status_error(anthropic.RateLimitError, 429), "rate_limit", True),
        (status_error(anthropic.AuthenticationError, 401), "auth", False),
        (status_error(anthropic.PermissionDeniedError, 403), "auth", False),
        (
            status_error(anthropic.APIStatusError, 402, {"type": "error", "error": {"type": "billing_error"}}),
            "credits",
            False,
        ),
        (status_error(anthropic.NotFoundError, 404), "bad_request", False),
        (status_error(anthropic.BadRequestError, 400), "bad_request", False),
        (status_error(anthropic.GatewayTimeoutError, 504), "timeout", True),
        (status_error(anthropic.OverloadedError, 529), "unavailable", True),
        (status_error(anthropic.InternalServerError, 500), "unavailable", True),
        (status_error(anthropic.ConflictError, 409), "internal", False),
        (anthropic.APITimeoutError(request=REQ), "timeout", True),
        (anthropic.APIConnectionError(request=REQ), "offline", True),
    ],
)
async def test_sdk_errors_map_to_brain_errors(config: Config, exc: Exception, kind: str, retryable: bool) -> None:
    brain, _, _, _ = await make_brain(config, [StubStream([], text_message(""), error=exc)])
    [event] = await collect(brain, "hi")
    assert isinstance(event, BrainError)
    assert (event.kind, event.retryable) == (kind, retryable)
    assert brain._history == []


async def test_history_is_bounded_and_trim_strips_thinking(config: Config) -> None:
    config.brain.history_turns = 4  # type: ignore[attr-defined]
    streams = [StubStream([f"r{i}"], text_message(f"r{i}")) for i in range(5)]
    brain, client, _, _ = await make_brain(config, streams)
    for i in range(5):
        await collect(brain, f"q{i}")
    last = client.requests[-1]["messages"]
    assert [m["content"] for m in last if m["role"] == "user"] == ["q2", "q3", "q4"]
    for m in last[:-1]:
        if m["role"] == "assistant":
            assert all(b["type"] != "thinking" for b in m["content"])


async def test_usage_is_charged_per_model_when_a_fallback_ran(config: Config) -> None:
    usage = {
        "input_tokens": 10,
        "output_tokens": 5,
        "iterations": [
            {"type": "message", "model": "claude-opus-5-5", "input_tokens": 1000, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 10, "output_tokens": 5,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        ],
    }
    final = text_message("ok", model="claude-opus-4-8", usage=usage)
    brain, _, budget, _ = await make_brain(config, [StubStream(["ok"], final)])
    events = await collect(brain, "hi", heavy=True)
    # Each model at its own price: Opus 5.5 for the first call, Opus 4.8 for the fallback.
    assert budget.spent_usd == pytest.approx((1000 * 4 + 10 * 5 + 5 * 25) / 1e6)
    assert events[-1].input_tokens == 1010


def test_echo_content_drops_internal_blocks_before_the_fallback() -> None:
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "a"},
        {"type": "text", "text": "Part"},
        {"type": "fallback", "from": {"model": "x"}, "to": {"model": "y"}},
        {"type": "thinking", "thinking": "", "signature": "b"},
        {"type": "text", "text": "Rest"},
    ]
    assert [b["type"] for b in echo_content(blocks)] == ["text", "fallback", "thinking", "text"]
    plain = [{"type": "thinking"}, {"type": "text"}]
    assert echo_content(plain) == plain
