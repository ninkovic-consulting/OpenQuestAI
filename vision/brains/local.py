"""The host's brain on the local model: the conversation, the tools, the short prompt.

The model itself lives in the shared `LocalEngine` (MLX in process, or an
OpenAI-compatible server), which the residents use too. This brain keeps the
host's conversation (the user's words and the replies, not the tool rounds,
so prompts stay short), writes the system prompt (the memory core, cut to
`local_rules.LOCAL_CORE_CHARS`, then the rule line for this model) and runs
the tool loop (`local_tools`) through the same `ToolHost` Claude uses, so
every call passes the gate. A model that cannot call tools is offered none
and is told so; a small model is offered the short list
(`local_rules.ESSENTIAL`).

No local model here reads images (`SEES_IMAGES`), so a message with images is
never sent to it: the brain answers with a plain line saying the model
answering now cannot see them (`local_rules.cannot_see`), and keeps that
exchange in its history like any other.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

from vision.brains import local_rules, local_tools
from vision.brains.engine import LocalEngine
from vision.brains.local_chat import Message, Reply, Request
from vision.brains.local_errors import LocalModelError
from vision.brains.pump import Emit, Pump
from vision.core.config import Config
from vision.core.events import BrainName
from vision.core.interfaces import (
    BrainError,
    BrainEvent,
    Memory,
    Picture,
    TextDelta,
    ToolHost,
    ToolResult,
    ToolSpec,
    TurnDone,
)

log = logging.getLogger(__name__)

DEFAULT_HISTORY_TURNS = 20
MAX_TOOL_ROUNDS = 6
SEES_IMAGES = False
"""Whether the local model can read images: no. mlx-lm loads only a model's text weights (the
catalog's entries with a vision encoder would need mlx-vlm, which is not installed), and the
OpenAI-compatible backend sends words only. `brain.mode` carries it as `local_images`."""


@dataclass
class _Turn:
    user: Message
    spoken: list[str] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class LocalBrain:
    def __init__(self, config: Config, memory: Memory, engine: LocalEngine, tools: ToolHost | None) -> None:
        self._config = config
        self._memory = memory
        self.engine = engine
        self._tools = tools
        extra = config.brain.model_extra or {}
        self._max_turns = max(1, int(extra.get("history_turns", DEFAULT_HISTORY_TURNS)))
        self._history: list[tuple[Message, Message]] = []
        self._pump = Pump()

    @property
    def name(self) -> BrainName:
        return "local"

    @property
    def model(self) -> str:
        return self.engine.model

    async def start(self) -> None:
        """In offline mode the model starts loading now, so the first message need not wait for
        it; otherwise the engine loads it on the first generation."""
        if self._config.brain.offline:
            self.engine.follow()

    async def interrupt(self) -> None:
        self._pump.stop()
        await self.engine.interrupt()

    async def close(self) -> None:
        await self.engine.close()

    async def offered(self) -> list[ToolSpec]:
        """The tools this model is given: none without tool support, the short list when small."""
        if self._tools is None or not await self.engine.can_call_tools():
            return []
        specs = self._tools.specs()
        if self.engine.small():
            specs = [s for s in specs if s.name in local_rules.ESSENTIAL]
        return specs

    async def send(
        self, text: str, *, heavy: bool = False, images: Sequence[Picture] = ()
    ) -> AsyncIterator[BrainEvent]:
        if images:
            line = local_rules.cannot_see(len(images), offline=self._config.brain.offline)
            yield TextDelta(line)
            self._commit({"role": "user", "content": f"{text}\n\n[{len(images)} image(s) not shown]"}, line)
            yield TurnDone(self.model, 0, 0, "end_turn")
            return
        turn = _Turn(user={"role": "user", "content": text})
        error: BrainError | None = None
        try:
            async with aclosing(self._pump.run(lambda emit: self._run(turn, heavy, emit))) as events:
                async for event in events:
                    yield event
        except LocalModelError as exc:
            error = exc.error
        finally:
            if error is None:
                self._commit(turn.user, "".join(turn.spoken).strip())
        if error is not None:
            yield error
            return
        stop = "interrupted" if self._pump.interrupted else turn.stop_reason
        yield TurnDone(self.model, turn.input_tokens, turn.output_tokens, stop)

    async def _run(self, turn: _Turn, heavy: bool, emit: Emit) -> None:
        specs = await self.offered()
        rules = local_rules.rules(tools=bool(specs), offline=self._config.brain.offline)
        core = local_rules.short_core(self._memory.core())
        spoken = turn.spoken

        def say(piece: str) -> None:
            if spoken and spoken[-1] == "" and piece and not piece[0].isspace():
                piece = " " + piece  # a new round starts after the last one's words
            spoken.append(piece)
            emit(TextDelta(piece))

        async def generate(messages: list[Message], offer: bool) -> Reply:
            if spoken and spoken[-1] != "" and not spoken[-1][-1].isspace():
                spoken.append("")
            request = Request(
                core=core,
                rules=rules,
                messages=messages,
                tools=specs if offer else [],
                max_tokens=self._config.brain.max_output_tokens,
                thinking=heavy,
            )
            return await self.engine.generate(request, "host", say)

        messages = [m for pair in self._history for m in pair] + [turn.user]
        loop = await local_tools.run(
            generate,
            self._tools.call if self._tools is not None else _refuse,
            specs,
            messages,
            max_rounds=MAX_TOOL_ROUNDS,
        )
        if loop.gave_up:
            say(("" if not spoken else " ") + local_tools.GAVE_UP)
        turn.stop_reason = loop.stop if loop.stop != "tool_use" else "end_turn"
        turn.input_tokens, turn.output_tokens = loop.input_tokens, loop.output_tokens

    def _commit(self, user: Message, said: str) -> None:
        if not said:
            return
        self._history.append((user, {"role": "assistant", "content": said}))
        if len(self._history) > self._max_turns:
            # The oldest quarter goes at once, so the beginning of the prompt (which the engine
            # keeps read) stays the same for several turns instead of changing on every one.
            del self._history[: len(self._history) - (self._max_turns - self._max_turns // 4)]


async def _refuse(name: str, args: dict[str, Any]) -> ToolResult:
    return ToolResult(False, "This brain has no tools.")
