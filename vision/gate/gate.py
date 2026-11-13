"""The gate: every tool call passes through here, and every call is audited.

- `free` runs at once (for `shell`, only in a turn the owner typed or said
  at the Mac; see `policy`).
- `ask` publishes `gate.request`, waits up to `[gate] timeout_s` for a
  matching `gate.decision`, then publishes `gate.resolved`. No answer is a
  deny, logged as `timeout`.
- `never` (and unknown tools) are refused.

During an automation's run the card names the automation, an `ask` that
nobody answers marks the run as having needed approval, and tools that may
not run unattended are refused before anyone is asked. Nothing an
automation does goes around the gate.

During a resident's job the calls go through a scoped gate (`scoped`): the
same tiers, audit and bus, the job's own tools, and an `Actor` that names the
agent and job on the card ("Tink, in the Workshop: run a program") and in
every audit row. All scopes share one list of waiting requests, so a spoken
or typed yes or no always settles the oldest, whoever asked. A scope's
`JobHooks` hear when a request opens and closes (the agent is waiting) and
when nobody answered (the job needed approval).

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
from dataclasses import dataclass
from typing import Any, Protocol

from vision.core.bus import Bus, Subscription
from vision.core.config import Config, Tier
from vision.core.events import GateChoice, GateDecision, GateOutcome, GateRequest, GateResolved
from vision.core.interfaces import AuditRecord, Memory, ToolResult, ToolSpec
from vision.core.turns import current_origin
from vision.gate.policy import tier_for
from vision.gate.tools import Tool, ToolFailure

log = logging.getLogger(__name__)

AUDIT_RESULT_LIMIT = 300
LINE_DETAIL = 90
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


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is calling, when it is a resident at work rather than the host."""

    agent: str
    agent_name: str
    job: str
    room_name: str | None = None

    def says(self, summary: str) -> str:
        """The card's summary in the agent's name: "Tink, in the Workshop: run a program"."""
        what = summary[:1].lower() + summary[1:]
        where = f", in the {self.room_name}" if self.room_name else ""
        return f"{self.agent_name}{where}: {what}"


class JobHooks(Protocol):
    def waiting(self, waiting: bool) -> None:
        """A request of this job opened (True) or closed (False)."""
        ...

    def unanswered(self) -> None:
        """A request of this job ran out of time with nobody answering."""
        ...


class ToolGate:
    def __init__(
        self,
        config: Config,
        bus: Bus,
        memory: Memory,
        tools: Sequence[Tool],
        *,
        actor: Actor | None = None,
        hooks: JobHooks | None = None,
        waiting: list[str] | None = None,
    ) -> None:
        self._config = config
        self._gate = config.gate
        self._bus = bus
        self._memory = memory
        self._tools = {tool.spec.name: tool for tool in tools}
        self._actor = actor
        self._hooks = hooks
        self._waiting: list[str] = [] if waiting is None else waiting

    def scoped(self, tools: Sequence[Tool], actor: Actor, hooks: JobHooks | None = None) -> ToolGate:
        """A gate for one job: its own tools, the same tiers, audit, bus and waiting list."""
        return ToolGate(
            self._config, self._bus, self._memory, tools, actor=actor, hooks=hooks, waiting=self._waiting
        )

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def tier(self, name: str) -> Tier:
        """The tier in the turn this runs in. A resident's call is never the owner's own turn,
        whichever turn handed the job off, so a tier free only at the Mac asks there."""
        origin = current_origin()
        source = origin.source if origin is not None and self._actor is None else None
        return tier_for(self._gate, name, source)

    def line(self, name: str, args: dict[str, Any]) -> str:
        """One line saying what a call does, for a job's steps: "Run a program: pytest -q"."""
        tool = self._tools.get(name)
        if tool is None:
            return name
        detail = _detail(tool, args)
        detail = " ".join(detail.split())
        if len(detail) > LINE_DETAIL:
            detail = detail[: LINE_DETAIL - 1].rstrip() + "…"
        return f"{tool.summary}: {detail}" if detail else tool.summary

    async def permit(self, name: str, summary: str, detail: str) -> bool:
        """Whether something that is not a local tool call may happen (the scout's server-side
        web search): `free` yes, `never` no, `ask` asks like a tool would. Audited."""
        tier = self.tier(name)
        args = {"detail": detail}
        if tier == "never":
            await self._audit(name, args, tier, "deny", "refused by policy")
            return False
        if tier == "free":
            return True
        request_id = uuid.uuid4().hex
        outcome = await self._ask(request_id, name, summary, detail)
        if outcome == "timeout" and self._hooks is not None:
            self._hooks.unanswered()
        await self._audit(name, args, tier, outcome, "allowed" if outcome == "allow" else "not allowed", request_id)
        return outcome == "allow"

    async def record(self, name: str, args: dict[str, Any], result: str) -> None:
        """Audit a use the gate allowed beforehand and that ran elsewhere (a server-side search)."""
        await self._audit(name, args, self.tier(name), "allow", result)

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
        tier = self.tier(name)
        tool = self._tools.get(name)
        if tool is None:
            await self._audit(name, args, tier, "deny", "unknown tool")
            return ToolResult(False, f"There is no tool called {name}.")
        if tier == "never":
            await self._audit(name, args, tier, "deny", "refused by policy")
            return ToolResult(False, "That action is not allowed.")
        origin = current_origin()
        if tool.unattended_refusal and origin is not None and origin.source == "automation":
            await self._audit(name, args, tier, "deny", "refused during an automation")
            return ToolResult(False, tool.unattended_refusal)
        request_id = ""
        if tier == "ask":
            request_id = uuid.uuid4().hex
            try:
                outcome = await self._ask(request_id, tool.spec.name, tool.summary, _detail(tool, args))
            except asyncio.CancelledError:
                await self._audit(name, args, tier, "deny", "cancelled", request_id)
                raise
            if outcome == "timeout":
                origin = current_origin()
                if self._hooks is not None:
                    self._hooks.unanswered()
                elif origin is not None and origin.source == "automation":
                    origin.needed_approval = True
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

    async def _ask(self, request_id: str, name: str, summary: str, detail: str) -> GateOutcome:
        timeout = self._gate.timeout_s
        actor = self._actor
        origin = current_origin()
        if actor is not None:
            summary = actor.says(summary)
        elif origin is not None and origin.source == "automation":
            summary = f'Automation "{origin.automation_name}": {summary}'
        sub = self._bus.subscribe({GateDecision.TYPE})
        self._waiting.append(request_id)
        if self._hooks is not None:
            self._hooks.waiting(True)
        outcome: GateOutcome = "deny"
        try:
            self._bus.publish(
                GateRequest(
                    id=request_id,
                    tool=name,
                    summary=summary,
                    detail=detail,
                    expires_at=time.time() + timeout,
                    agent=actor.agent if actor else None,
                    agent_name=actor.agent_name if actor else None,
                    job=actor.job if actor else None,
                )
            )
            try:
                outcome = await asyncio.wait_for(self._decision(sub, request_id), timeout)
            except TimeoutError:
                outcome = "timeout"
        finally:
            sub.close()
            self._waiting.remove(request_id)
            if self._hooks is not None:
                self._hooks.waiting(False)
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
        actor = self._actor
        entry = AuditRecord(
            ts=time.time(),
            tool=tool,
            args=args,
            tier=tier,
            decision=decision,
            result=result[:AUDIT_RESULT_LIMIT],
            request_id=request_id,
            agent=actor.agent if actor else "",
            job=actor.job if actor else "",
        )
        try:
            await self._memory.audit(entry)
        except Exception:
            log.exception("could not audit a %s call", tool)


def _detail(tool: Tool, args: dict[str, Any]) -> str:
    """Words for the card's detail: the tool's own, its detail argument, else the arguments."""
    detail = tool.describe(args) if tool.describe is not None else args.get(tool.detail_arg)
    if not isinstance(detail, str):
        detail = json.dumps(args, sort_keys=True, ensure_ascii=False)
    return detail
