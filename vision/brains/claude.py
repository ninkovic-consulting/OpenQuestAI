"""The Claude brain: the Anthropic API through the official async SDK, streamed.

One `send` is one user turn. It streams the reply, runs the tool loop through
the injected `ToolHost` (so the gate decides every call), records every model
call's usage on the `Budget`, and appends the turn to the conversation history.

Prompt caching: the system prompt is the memory core with an explicit
breakpoint, and top-level automatic caching covers the growing conversation.
The system prompt is frozen for the life of the conversation history: Claude
models bind replayed thinking blocks to the exact prefix, so it is refreshed
only when the history is trimmed (which strips those blocks anyway). Nothing
volatile goes into it.

History stays append-only between trims. A turn that did not finish normally
(interrupted, refused, cut off mid tool call) is stored as the user's message
plus the text that was actually said, so the transcript is always valid.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

import anthropic

from vision.brains.claude_errors import to_brain_error
from vision.brains.models import HostModels, host_models
from vision.brains.pump import Emit, Pump
from vision.core.config import Config
from vision.core.events import BrainName
from vision.core.interfaces import (
    BrainError,
    BrainEvent,
    Budget,
    Memory,
    TextDelta,
    ToolHost,
    TurnDone,
)
from vision.core.secrets import get_api_key

log = logging.getLogger(__name__)

TALK_EFFORT = "low"
HEAVY_EFFORT = "high"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 8
DEFAULT_HISTORY_TURNS = 20
DEFAULT_HEAVY_MAX_TOKENS = 8192
REFUSAL_LINE = "I can't help with that one."
_THINKING = frozenset({"thinking", "redacted_thinking"})

ClientFactory = Callable[[str, float], Any]
Message = dict[str, Any]


def default_client(api_key: str, timeout: float) -> anthropic.AsyncAnthropic:
    # The router does the single retry, so the SDK's own retries are off.
    return anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=timeout)


def supports_fallbacks(model: str) -> bool:
    """Models that take the server-side refusal `fallbacks` parameter (not Haiku)."""
    return model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5"))


def echo_content(blocks: list[Message]) -> list[Message]:
    """Content to send back: after a mid-output fallback, drop the model-internal
    blocks that precede the last `fallback` block (which itself stays in place)."""
    last = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    return [
        b
        for i, b in enumerate(blocks)
        if i > last or b.get("type") not in _THINKING | {"tool_use"}
    ]


def _without_thinking(message: Message) -> Message | None:
    content = message["content"]
    if message["role"] != "assistant" or isinstance(content, str):
        return message
    kept = [b for b in content if b.get("type") not in _THINKING]
    return {**message, "content": kept} if kept else None


@dataclass
class _Turn:
    model: str
    heavy: bool
    messages: list[Message]
    spoken: list[str] = field(default_factory=list)
    complete: bool = False
    fresh_call: bool = False
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class ClaudeBrain:
    """Talks with Claude. `has_key` is False until a key is found."""

    def __init__(
        self,
        config: Config,
        tools: ToolHost,
        memory: Memory,
        budget: Budget,
        *,
        client_factory: ClientFactory = default_client,
    ) -> None:
        self._config = config
        self._tools = tools
        self._memory = memory
        self._budget = budget
        self._client_factory = client_factory
        self._models = HostModels(config.brain.talk_model, config.brain.heavy_model)
        extra = config.brain.model_extra or {}
        self._max_turns = max(2, int(extra.get("history_turns", DEFAULT_HISTORY_TURNS)))
        self._heavy_max_tokens = int(extra.get("heavy_max_output_tokens", DEFAULT_HEAVY_MAX_TOKENS))
        self._client: Any = None
        self._history: list[list[Message]] = []
        self._system: str | None = None
        self._pump = Pump()

    @property
    def name(self) -> BrainName:
        return "claude"

    @property
    def has_key(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        self._models = host_models(self._config)
        await self.reload_key()

    async def reload_key(self) -> bool:
        """Look for a key again (after `vision auth`). True when a client is ready."""
        if self._client is None:
            key = await asyncio.to_thread(get_api_key)
            if key:
                self._client = self._client_factory(key, self._config.brain.request_timeout_s)
        return self._client is not None

    async def interrupt(self) -> None:
        self._pump.stop()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    # ------------------------------------------------------------ one turn

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        if self._client is None:
            yield BrainError("auth", "No Anthropic API key is stored. Run `vision auth`.", False)
            return
        self._trim()
        if self._system is None:
            self._system = self._memory.core()
        model = self._models.heavy if heavy else self._models.talk
        turn = _Turn(model=model, heavy=heavy, messages=[{"role": "user", "content": text}])
        error: BrainError | None = None
        said: list[str] = []
        try:
            async with aclosing(self._pump.run(lambda emit: self._run(turn, emit))) as events:
                async for event in events:
                    if isinstance(event, TextDelta):
                        said.append(event.text)
                    yield event
        except Exception as exc:
            log.warning("claude turn failed: %s", type(exc).__name__)
            error = to_brain_error(exc)
        finally:
            if error is None:
                self._commit(turn, said)
        if error is not None:
            yield error
            return
        stop = "interrupted" if self._pump.interrupted else turn.stop_reason
        yield TurnDone(turn.model, turn.input_tokens, turn.output_tokens, stop)

    async def _run(self, turn: _Turn, emit: Emit) -> None:
        for round_no in range(MAX_TOOL_ROUNDS):
            message = await self._call(turn, emit, allow_tools=round_no < MAX_TOOL_ROUNDS - 1)
            turn.stop_reason = message.stop_reason or "end_turn"
            turn.model = message.model
            if message.stop_reason == "refusal":
                turn.fresh_call = True  # keep the line apart from any partial text
                self._say(turn, emit, REFUSAL_LINE)
                return
            content = echo_content([block.to_dict() for block in message.content])
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if message.stop_reason == "max_tokens" and tool_uses:
                return  # a truncated tool input must not run
            if content:
                turn.messages.append({"role": "assistant", "content": content})
            if message.stop_reason == "pause_turn":
                continue
            if message.stop_reason != "tool_use" or not tool_uses:
                turn.complete = True
                return
            results = [await self._tool_result(block) for block in tool_uses]
            turn.messages.append({"role": "user", "content": results})

    async def _call(self, turn: _Turn, emit: Emit, *, allow_tools: bool) -> Any:
        kwargs: dict[str, Any] = {
            "model": turn.model,
            "max_tokens": (
                self._heavy_max_tokens if turn.heavy else self._config.brain.max_output_tokens
            ),
            "messages": [m for past in self._history for m in past] + turn.messages,
            "output_config": {"effort": HEAVY_EFFORT if turn.heavy else TALK_EFFORT},
            "cache_control": {"type": "ephemeral"},
        }
        if self._system:
            kwargs["system"] = [
                {"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}
            ]
        tools = [
            {"name": s.name, "description": s.description, "input_schema": s.input_schema}
            for s in self._tools.specs()
        ]
        if tools:
            kwargs["tools"] = tools
            if not allow_tools:
                kwargs["tool_choice"] = {"type": "none"}
        if supports_fallbacks(turn.model):
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        turn.fresh_call = bool(turn.spoken)
        async with self._client.beta.messages.stream(**kwargs) as stream:
            try:
                async for event in stream:
                    if event.type == "text" and event.text:
                        self._say(turn, emit, event.text)
                return await stream.get_final_message()
            finally:
                self._record(turn, stream)

    def _say(self, turn: _Turn, emit: Emit, text: str) -> None:
        if turn.fresh_call:
            turn.fresh_call = False
            if turn.spoken and not turn.spoken[-1][-1].isspace() and not text[0].isspace():
                text = " " + text
        turn.spoken.append(text)
        emit(TextDelta(text))

    def _record(self, turn: _Turn, stream: Any) -> None:
        """Charge the budget for one model call, per model when a fallback ran."""
        try:
            snapshot = stream.current_message_snapshot
        except AssertionError:  # no message_start yet: nothing was billed
            return
        usage = snapshot.usage
        parts = [i for i in (usage.iterations or []) if getattr(i, "model", None)] or [usage]
        for part in parts:
            model = getattr(part, "model", None) or snapshot.model
            fresh = part.input_tokens or 0
            out = part.output_tokens or 0
            read = part.cache_read_input_tokens or 0
            write = part.cache_creation_input_tokens or 0
            self._budget.record(model, fresh, out, cache_read_tokens=read, cache_write_tokens=write)
            turn.input_tokens += fresh + read + write
            turn.output_tokens += out

    async def _tool_result(self, block: Message) -> Message:
        args = block.get("input")
        result = await self._tools.call(block["name"], args if isinstance(args, dict) else {})
        return {
            "type": "tool_result",
            "tool_use_id": block["id"],
            "content": result.content or "(no output)",
            "is_error": not result.ok,
        }

    # ------------------------------------------------------------ history

    def _commit(self, turn: _Turn, said: list[str]) -> None:
        """Store the whole turn, or only what the user actually heard if it ended early."""
        if turn.complete and not self._pump.interrupted:
            self._history.append(turn.messages)
            return
        text = REFUSAL_LINE if turn.stop_reason == "refusal" else "".join(said).strip()
        if text:
            reply = {"role": "assistant", "content": [{"type": "text", "text": text}]}
            self._history.append([turn.messages[0], reply])

    def _trim(self) -> None:
        """Keep the history bounded: drop the oldest half and every thinking block."""
        if len(self._history) < self._max_turns:
            return
        kept = self._history[-(self._max_turns // 2) :]
        self._history = [
            [m for m in (_without_thinking(msg) for msg in past) if m is not None] for past in kept
        ]
        self._system = None
