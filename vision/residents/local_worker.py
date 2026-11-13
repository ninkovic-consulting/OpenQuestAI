"""One job on the local model: the resident's own session, through the same gate and board.

Used in offline mode, and when Claude cannot be used for a job (no API key,
or the month's budget is used up) while the local model can call tools. The
loop is `vision.brains.local_tools`: each generation is a step, tool calls
are checked before they run and go through the job's scoped gate (tiers,
audit, the owner's yes), and a call the model writes wrongly is answered
with an error, never run on a guess. Generations wait their turn in the
shared engine, behind the host's. Nothing is charged: the model runs on this
Mac. Server-side web search does not exist here, and the rule line says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from vision.brains import local_rules, local_tools
from vision.brains.engine import LocalEngine
from vision.brains.local_chat import Message, Reply, Request
from vision.brains.local_errors import LocalModelError
from vision.core.interfaces import ToolResult
from vision.gate.gate import ToolGate
from vision.jobs import Desk, Outcome
from vision.jobs.model import clip
from vision.residents.worker import OWN_STEPS

log = logging.getLogger(__name__)

LOCAL_MAX_TOKENS = 4096
TOOL_RESULT_MAX = 8000
"""A local model's context is small; a long file is cut sooner than for Claude."""


@dataclass(frozen=True, slots=True)
class LocalSession:
    system: str
    opening: str
    careful: bool
    max_steps: int
    offline: bool


async def work_local(engine: LocalEngine, gate: ToolGate, desk: Desk, s: LocalSession) -> Outcome:
    """Run the job's tool loop on the local model and say how it went."""
    rules = local_rules.resident_rules(offline=s.offline)
    specs = gate.specs()
    said: list[str] = []

    async def generate(messages: list[Message], offer: bool) -> Reply:
        request = Request(
            core=s.system,
            rules=rules,
            messages=messages,
            tools=specs if offer else [],
            max_tokens=LOCAL_MAX_TOKENS,
            thinking=s.careful,
        )
        reply = await engine.generate(request, "job")
        if reply.text.strip():
            said.append(reply.text.strip())
            desk.partial = "\n\n".join(said)
        return reply

    async def call(name: str, args: dict[str, Any]) -> ToolResult:
        line = gate.line(name, args)
        result = await gate.call(name, args)
        if name not in OWN_STEPS or not result.ok:
            desk.step("tool", line if result.ok else f"{line} (did not work: {clip(result.content, 100)})")
        return result

    messages: list[Message] = [{"role": "user", "content": s.opening}]
    try:
        loop = await local_tools.run(
            generate, call, specs, messages, max_rounds=s.max_steps, clip=lambda t: clip(t, TOOL_RESULT_MAX)
        )
    except LocalModelError as exc:
        log.warning("job %s: the local model failed (%s)", desk.job.id, exc.error.kind)
        return Outcome("failed", desk.partial, exc.error.message)
    if loop.gave_up:
        return Outcome("failed", desk.partial, local_tools.GAVE_UP)
    if loop.stop == "max_tokens":
        return Outcome("failed", desk.partial, "Its answer was cut off at the output limit.")
    if loop.rounds >= s.max_steps and not loop.text:
        return Outcome("failed", desk.partial, f"It used all {s.max_steps} steps without finishing.")
    return Outcome("done", loop.text or desk.partial)
