"""The brain the session talks to: Claude first, the local model behind it.

- A rate limit, timeout, outage or lost network is retried once on Claude.
- If Claude still cannot answer (or the key is rejected, or credit is gone),
  the turn goes to the local model, `brain.fallback` is published, and Claude
  is tried again after `[brain] retry_claude_after_s`.
- No key, no SDK, an exhausted monthly budget or exhausted credit means the
  local model from the start, with a `notice` that says why.
- The first local reply after a switch begins with a short spoken line saying
  so, and `name` always reports the backend answering now.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import TYPE_CHECKING

from vision.brains.local import LocalBrain
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BrainFallback, BrainName, Notice
from vision.core.interfaces import BrainError, BrainEvent, Budget, TextDelta

if TYPE_CHECKING:  # the SDK is an optional extra; the router runs without it
    from vision.brains.claude import ClaudeBrain

FALLBACK_KINDS = frozenset({"rate_limit", "auth", "credits", "timeout", "offline", "unavailable"})
LOCAL_LINE = "I'm running on the local model right now. "


class Router:
    def __init__(
        self,
        config: Config,
        bus: Bus,
        claude: ClaudeBrain | None,
        local: LocalBrain,
        budget: Budget,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = config.assistant.name
        self._cooldown = config.brain.retry_claude_after_s
        self._bus = bus
        self._claude = claude
        self._local = local
        self._budget = budget
        self._clock = clock
        self._current: BrainName = "claude"
        self._retry_at = 0.0
        self._probing = False
        self._announce = False
        self._credits_month: str | None = None

    @property
    def name(self) -> BrainName:
        return self._current

    async def start(self) -> None:
        await self._local.start()
        if self._claude is not None:
            await self._claude.start()
        reason = self._blocker()
        if reason is not None:
            self._current = "local"
            self._announce = True
            self._bus.publish(Notice(level="warn", text=reason))

    async def interrupt(self) -> None:
        if self._claude is not None:
            await self._claude.interrupt()
        await self._local.interrupt()

    async def close(self) -> None:
        if self._claude is not None:
            await self._claude.close()
        await self._local.close()

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        if self._claude is not None and await self._use_claude():
            failure: BrainError | None = None
            for attempt in range(2):
                failure, spoke = None, False
                async with aclosing(self._claude.send(text, heavy=heavy)) as events:
                    async for event in events:
                        if isinstance(event, BrainError):
                            failure = event
                            break
                        spoke = True
                        yield event
                if failure is None:
                    self._recovered()
                    return
                if spoke or failure.kind not in FALLBACK_KINDS:
                    if failure.kind in FALLBACK_KINDS:
                        self._fall_back(failure)
                    yield failure
                    return
                if not (attempt == 0 and failure.retryable):
                    break
            assert failure is not None
            self._fall_back(failure)
        first = True
        async with aclosing(self._local.send(text, heavy=heavy)) as events:
            async for event in events:
                if first and self._announce and isinstance(event, TextDelta):
                    self._announce = False
                    yield TextDelta(LOCAL_LINE)
                first = False
                yield event

    # ------------------------------------------------------------ switching

    def _blocker(self) -> str | None:
        """Why Claude cannot be used right now, as a notice for the user, or None."""
        if self._claude is None:
            return (
                f"The Anthropic SDK is not installed, so {self._name} is running on the local "
                "model. Install it with `uv sync --extra brains`."
            )
        if not self._claude.has_key:
            return (
                f"{self._name} has no Anthropic API key yet and is running on the local model. "
                "Run `vision auth` to add one."
            )
        if self._budget.exhausted():
            return (
                f"This month's API budget is used up, so {self._name} is running on the local "
                "model. Raise [budget] monthly_cap_usd in config.toml to continue on Claude."
            )
        if self._credits_month == self._budget.status().month:
            return (
                f"The Anthropic account is out of credit, so {self._name} stays on the local "
                "model until next month's credit arrives."
            )
        return None

    async def _use_claude(self) -> bool:
        assert self._claude is not None
        if self._current == "claude":
            reason = self._blocker()
            if reason is None:
                return True
            self._switch_to_local(reason)
            return False
        if self._clock() < self._retry_at:
            return False
        if not self._claude.has_key:
            await self._claude.reload_key()
        if self._blocker() is not None:
            self._retry_at = self._clock() + self._cooldown
            return False
        self._current = "claude"
        self._probing = True
        return True

    def _switch_to_local(self, reason: str) -> None:
        self._current = "local"
        self._retry_at = self._clock() + self._cooldown
        self._announce = True
        self._bus.publish(BrainFallback(from_="claude", to="local", reason=reason))

    def _fall_back(self, failure: BrainError) -> None:
        if failure.kind == "credits":
            self._credits_month = self._budget.status().month
            self._bus.publish(Notice(level="warn", text=self._blocker() or failure.message))
        if self._probing:
            # Claude was only being tried again; the window already shows local.
            self._probing = False
            self._current = "local"
            self._retry_at = self._clock() + self._cooldown
            self._announce = True
            return
        self._switch_to_local(failure.message)

    def _recovered(self) -> None:
        if self._probing:
            self._probing = False
            self._bus.publish(
                BrainFallback(from_="local", to="claude", reason="Claude is answering again.")
            )
