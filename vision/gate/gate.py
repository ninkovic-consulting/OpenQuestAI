"""The gate: every tool call passes through here, and every call is audited.

- `free` runs at once.
- `ask` publishes `gate.request`, waits up to `[gate] timeout_s` for a
  matching `gate.decision`, then publishes `gate.resolved`. No answer is a
  deny, logged as `timeout`.
- `never` (and unknown tools) are refused.

The bus subscription for `gate.decision` is opened only while a request is
waiting. `answer(text)` lets a caller settle the waiting request from a spoken
or typed yes or no; it publishes the same `gate.decision` the window would.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Sequence
from typing import Any

from vision.core.bus import Bus, Subscription
from vision.core.config import Config
from vision.core.events import GateChoice, GateDecision, GateOutcome, GateRequest, GateResolved
from vision.core.interfaces import AuditRecord, Memory, ToolResult, ToolSpec
from vision.gate.policy import tier_for
from vision.gate.tools import Tool, ToolFailure

log = logging.getLogger(__name__)

AUDIT_RESULT_LIMIT = 300
_YES = frozenset({"yes", "yeah", "yep", "sure", "ok", "okay", "allow", "approve", "approved"})
_NO = frozenset({"no", "nope", "deny", "denied", "don't", "dont", "cancel", "stop", "decline"})


MAX_ANSWER_WORDS = 4


def parse_yes_no(text: str) -> GateChoice | None:
    """`allow` for a clear yes, `deny` for a clear no, None when unclear or mixed.

    Only a short reply counts. A longer sentence that happens to contain
    "ok" or "sure" is somebody talking about something else, and must never
    approve an action.
    """
    lowered = text.lower()
    found = re.findall(r"[a-z']+", lowered)
    if not found or len(found) > MAX_ANSWER_WORDS:
        return None
    words = set(found)
    yes = bool(words & _YES) or "go ahead" in lowered or "do it" in lowered
    no = bool(words & _NO)
    if yes == no:
        return None
    return "allow" if yes else "deny"


class ToolGate:
    def __init__(self, config: Config, bus: Bus, memory: Memory, tools: Sequence[Tool]) -> None:
        self._gate = config.gate
        self._bus = bus
        self._memory = memory
        self._tools = {tool.spec.name: tool for tool in tools}
        self._waiting: list[str] = []

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    @property
    def waiting(self) -> bool:
        """True while a request waits for the user's answer."""
        return bool(self._waiting)

    def answer(self, text: str) -> bool:
        """Settle the oldest waiting request from a spoken or typed reply.

        Returns True when `text` was a clear yes or no and a request was
        waiting (the caller should then not treat `text` as a new turn).
        """
        choice = parse_yes_no(text)
        if choice is None or not self._waiting:
            return False
        self._bus.publish(GateDecision(id=self._waiting[0], decision=choice))
        return True

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        tier = tier_for(self._gate, name)
        tool = self._tools.get(name)
        if tool is None:
            await self._audit(name, args, tier, "deny", "unknown tool")
            return ToolResult(False, f"There is no tool called {name}.")
        if tier == "never":
            await self._audit(name, args, tier, "deny", "refused by policy")
            return ToolResult(False, "That action is not allowed.")
        request_id = ""
        if tier == "ask":
            request_id = uuid.uuid4().hex
            try:
                outcome = await self._ask(request_id, tool, args)
            except asyncio.CancelledError:
                await self._audit(name, args, tier, "deny", "cancelled", request_id)
                raise
            if outcome == "timeout":
                await self._audit(name, args, tier, "timeout", "no answer", request_id)
                return ToolResult(
                    False, f"Nobody answered within {self._gate.timeout_s:g} seconds, so it did not run."
                )
            if outcome == "deny":
                await self._audit(name, args, tier, "deny", "declined by the user", request_id)
                return ToolResult(False, "The user declined, so it did not run.")
        result = await self._run(tool, args)
        await self._audit(name, args, tier, "allow", result.content, request_id)
        return result

    async def _ask(self, request_id: str, tool: Tool, args: dict[str, Any]) -> GateOutcome:
        timeout = self._gate.timeout_s
        detail = args.get(tool.detail_arg)
        if not isinstance(detail, str):
            detail = json.dumps(args, sort_keys=True, ensure_ascii=False)
        sub = self._bus.subscribe({GateDecision.TYPE})
        self._waiting.append(request_id)
        outcome: GateOutcome = "deny"
        try:
            self._bus.publish(
                GateRequest(
                    id=request_id,
                    tool=tool.spec.name,
                    summary=tool.summary,
                    detail=detail,
                    expires_at=time.time() + timeout,
                )
            )
            try:
                outcome = await asyncio.wait_for(self._decision(sub, request_id), timeout)
            except TimeoutError:
                outcome = "timeout"
        finally:
            sub.close()
            self._waiting.remove(request_id)
            self._bus.publish(GateResolved(id=request_id, decision=outcome))
        return outcome

    @staticmethod
    async def _decision(sub: Subscription, request_id: str) -> GateOutcome:
        async for event in sub:
            if isinstance(event, GateDecision) and event.id == request_id:
                return event.decision
        raise RuntimeError("gate subscription ended")

    async def _run(self, tool: Tool, args: dict[str, Any]) -> ToolResult:
        try:
            return ToolResult(True, await tool.run(args) or "Done.")
        except ToolFailure as exc:
            return ToolResult(False, str(exc))
        except Exception as exc:
            log.exception("tool %s failed", tool.spec.name)
            return ToolResult(False, f"{tool.spec.name} failed ({type(exc).__name__}).")

    async def _audit(
        self,
        tool: str,
        args: dict[str, Any],
        tier: str,
        decision: GateOutcome,
        result: str,
        request_id: str = "",
    ) -> None:
        entry = AuditRecord(
            ts=time.time(),
            tool=tool,
            args=args,
            tier=tier,
            decision=decision,
            result=result[:AUDIT_RESULT_LIMIT],
            request_id=request_id,
        )
        try:
            await self._memory.audit(entry)
        except Exception:
            log.exception("could not audit a %s call", tool)
