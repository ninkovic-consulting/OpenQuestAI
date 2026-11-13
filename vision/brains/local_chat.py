"""What one generation on a local model takes and gives, and the turnstile in front of it.

A local model is one process on one GPU, so one generation runs at a time.
`Turnstile` hands the model out in turn, and a host turn always goes before a
resident's job that waits: the owner is waiting on the host, nobody waits on
a job's next step.

Messages are in the OpenAI chat shape that Hugging Face chat templates and
OpenAI-compatible servers both read: `{"role", "content"}`, an assistant's
`tool_calls` (`[{"id", "type": "function", "function": {"name", "arguments"}}]`
with `arguments` a dict) and `{"role": "tool", "tool_call_id", "name",
"content"}` for a result.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from vision.core.events import LocalLoad
from vision.core.interfaces import ToolSpec

Who = Literal["host", "job"]
ORDER: tuple[Who, ...] = ("host", "job")
Message = dict[str, Any]
OnText = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Request:
    """One generation. `core` may be cut short to fit the model's context; `rules` never is."""

    core: str
    rules: str
    messages: list[Message]
    tools: list[ToolSpec]
    max_tokens: int
    thinking: bool = False
    """Let a model that thinks before answering do so (heavy turns and jobs)."""


@dataclass(frozen=True, slots=True)
class Call:
    """A tool call as the model wrote it. `problem` says why it cannot be run, if it cannot."""

    id: str
    name: str
    arguments: dict[str, Any]
    problem: str = ""
    raw: str = ""


@dataclass(slots=True)
class Reply:
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop: str = "end_turn"
    """`end_turn`, `tool_use`, `max_tokens` or `interrupted`."""


@dataclass(frozen=True, slots=True)
class Status:
    """The local model as the window shows it: in memory or not, and what it is doing."""

    state: LocalLoad = "unloaded"
    weights_bytes: int | None = None
    """The memory the loaded weights hold."""
    cache_bytes: int = 0
    """The memory the kept prompts hold (`prompt_cache`)."""
    reading: tuple[int, int] | None = None
    """While a long prompt is read before the first word: tokens read and to read."""
    problem: str | None = None
    """Why the last load failed."""


def openai_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Tool specs in the shape chat templates and OpenAI-compatible servers read."""
    return [
        {
            "type": "function",
            "function": {"name": s.name, "description": s.description, "parameters": s.input_schema},
        }
        for s in specs
    ]


class Turnstile:
    """One holder at a time; a waiting host goes before every waiting job."""

    def __init__(self) -> None:
        self._held = False
        self._waiting: dict[Who, deque[asyncio.Future[None]]] = {"host": deque(), "job": deque()}

    @property
    def busy(self) -> bool:
        return self._held

    @asynccontextmanager
    async def turn(self, who: Who) -> AsyncIterator[None]:
        if self._held or any(self._waiting.values()):
            ticket: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiting[who].append(ticket)
            try:
                await ticket
            except asyncio.CancelledError:
                if ticket.done() and not ticket.cancelled():
                    self._next()  # it was handed the turn as it was cancelled: pass it on
                else:
                    self._waiting[who].remove(ticket)
                raise
        else:
            self._held = True
        try:
            yield
        finally:
            self._next()

    def _next(self) -> None:
        for who in ORDER:
            queue = self._waiting[who]
            while queue:
                ticket = queue.popleft()
                if not ticket.done():
                    ticket.set_result(None)
                    return
        self._held = False
