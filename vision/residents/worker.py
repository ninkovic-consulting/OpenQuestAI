"""One job's conversation with Claude: the resident's own session, apart from the host's.

The same stack as the host's brain (`vision.brains.claude`): the official
async SDK, streamed, the refusal fallback where the model takes it, the
system prompt cached with an explicit breakpoint and the growing transcript
with top-level automatic caching, and every call charged to the budget. The
loop is a job's, not a conversation's: one brief in, tool rounds through the
job's own scoped gate, and the resident's final words out as the result.

Each model call is a step. The job stops, failed, with what was done so far
when it has made `[jobs] max_steps` calls (the last call may use no tools,
so the resident sums up), when its own cost passes `[jobs] max_job_usd`, when
the month's budget is used up, or when the model declines. Server-side web
searches (the scout's) are shown as steps, audited, and charged per search.

Text is not streamed to anyone, so each call waits for the whole message;
streaming still keeps long calls clear of HTTP timeouts. Tool input is not
streamed eagerly (`eager_input_streaming`): a file the resident writes must
never arrive cut short, and nothing shows input as it is typed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from vision.brains.claude import FALLBACK_BETA, charge, echo_content, supports_fallbacks
from vision.brains.claude_errors import to_brain_error
from vision.core.interfaces import Budget
from vision.gate.gate import ToolGate
from vision.jobs import Desk, Outcome
from vision.jobs.model import clip

log = logging.getLogger(__name__)

ClientSource = Callable[[], Awaitable[Any | None]]
"""The SDK client for residents, or None when no API key is stored."""

NORMAL_EFFORT = "medium"
CAREFUL_EFFORT = "high"
NORMAL_MAX_TOKENS = 8192
CAREFUL_MAX_TOKENS = 16000
RETRY_AFTER_S = 2.0
TOOL_RESULT_MAX = 30_000
OWN_STEPS = frozenset({"note_progress", "ask_resident"})
"""Tools that put their own line on the job's record."""
WEB_SEARCH_DYNAMIC = "web_search_20260209"
WEB_SEARCH_BASIC = "web_search_20250305"
_DYNAMIC_SEARCH_MODELS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)
"""Models documented for the dynamic-filtering web search; the rest take the basic one."""


def web_search_tool(model: str, max_uses: int) -> dict[str, Any]:
    kind = WEB_SEARCH_DYNAMIC if model.startswith(_DYNAMIC_SEARCH_MODELS) else WEB_SEARCH_BASIC
    return {"type": kind, "name": "web_search", "max_uses": max_uses}


@dataclass(frozen=True, slots=True)
class Session:
    """What one job's conversation is made of."""

    model: str
    careful: bool
    system: str
    opening: str
    server_tools: list[dict[str, Any]]
    max_steps: int
    max_job_usd: float


async def work(client: Any, gate: ToolGate, desk: Desk, budget: Budget, s: Session) -> Outcome:
    """Run the job's tool loop to its end and say how it went."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": s.opening}]
    said: list[str] = []
    tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in gate.specs()
    ] + s.server_tools
    for step in range(s.max_steps):
        if budget.exhausted():
            return Outcome("failed", desk.partial, "This month's API budget ran out during the work.")
        last = step == s.max_steps - 1
        kwargs = _request(s, messages, tools, last=last)
        try:
            message, over = await _call(client, kwargs, budget, desk)
        except Exception as exc:
            error = to_brain_error(exc)
            log.warning("job %s: the model call failed (%s)", desk.job.id, error.kind)
            return Outcome("failed", desk.partial, error.message)
        content = echo_content([block.to_dict() for block in message.content])
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if text:
            said.append(text)
            desk.partial = "\n\n".join(said)
        await _searches(content, gate, desk)
        if message.stop_reason == "refusal":
            return Outcome("failed", desk.partial, "The model declined this work.")
        if over:
            return Outcome(
                "failed", desk.partial, f"Its cost passed the ${s.max_job_usd:.2f} cap for one job, so it was stopped."
            )
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if message.stop_reason == "max_tokens" and tool_uses:
            return Outcome("failed", desk.partial, "Its answer was cut off at the output limit.")
        if content:
            messages.append({"role": "assistant", "content": content})
        if message.stop_reason == "pause_turn" and not last:
            continue
        if message.stop_reason != "tool_use" or not tool_uses:
            if last:
                return Outcome("failed", text or desk.partial, f"It used all {s.max_steps} steps without finishing.")
            return Outcome("done", text or desk.partial)
        messages.append({"role": "user", "content": [await _run_tool(gate, desk, b) for b in tool_uses]})
    return Outcome("failed", desk.partial, f"It used all {s.max_steps} steps without finishing.")


def _request(s: Session, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, last: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": s.model,
        "max_tokens": CAREFUL_MAX_TOKENS if s.careful else NORMAL_MAX_TOKENS,
        "system": [{"type": "text", "text": s.system, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "output_config": {"effort": CAREFUL_EFFORT if s.careful else NORMAL_EFFORT},
        "cache_control": {"type": "ephemeral"},
    }
    if tools:
        kwargs["tools"] = tools
        if last:
            kwargs["tool_choice"] = {"type": "none"}  # the last step sums up
    if supports_fallbacks(s.model):
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    return kwargs


async def _call(client: Any, kwargs: dict[str, Any], budget: Budget, desk: Desk) -> tuple[Any, bool]:
    """One model call, retried once after a short pause when the failure is passing."""
    for attempt in range(2):
        over = False
        try:
            async with client.beta.messages.stream(**kwargs) as stream:
                try:
                    message = await stream.get_final_message()
                finally:
                    over = desk.charge(charge(budget, stream).usd)
            return message, over
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt == 0 and to_brain_error(exc).retryable:
                await asyncio.sleep(RETRY_AFTER_S)
                continue
            raise
    raise AssertionError("unreachable")


async def _searches(content: list[dict[str, Any]], gate: ToolGate, desk: Desk) -> None:
    for block in content:
        if block.get("type") == "server_tool_use" and block.get("name") == "web_search":
            query = str((block.get("input") or {}).get("query", ""))
            desk.step("tool", f"Searched the web: {clip(query, 120)}")
            await gate.record("web_search", {"query": query}, "searched")


async def _run_tool(gate: ToolGate, desk: Desk, block: dict[str, Any]) -> dict[str, Any]:
    name = str(block["name"])
    given = block.get("input")
    args: dict[str, Any] = given if isinstance(given, dict) else {}
    line = gate.line(name, args)
    result = await gate.call(name, args)
    if name not in OWN_STEPS or not result.ok:
        desk.step("tool", line if result.ok else f"{line} (did not work: {clip(result.content, 100)})")
    return {
        "type": "tool_result",
        "tool_use_id": block["id"],
        "content": clip(result.content, TOOL_RESULT_MAX) or "(no output)",
        "is_error": not result.ok,
    }
