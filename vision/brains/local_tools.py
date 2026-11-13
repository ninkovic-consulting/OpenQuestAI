"""The tool loop on a local model, shared by the host's local brain and a resident's local job.

Each round is one generation. Every call the model writes is checked before
anything runs: the tool must be one it was offered, the arguments a JSON
object with the required keys, no keys the schema forbids, and simple types
that match. A call that fails the check, or that could not be read at all,
is never run on a guess: the model is told what was wrong and may try again,
at most `MAX_BAD` times in one loop, after which the loop ends with what
was said. Calls that pass go to `call`, which is the gate (tiers, audit,
limits), exactly as Claude's do. The last round offers no tools, so the
model sums up.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from vision.brains.local_chat import Call, Message, Reply
from vision.core.interfaces import ToolResult, ToolSpec

MAX_BAD = 2
"""Malformed or invalid calls answered with an error in one loop before it gives up."""
GAVE_UP = "The local model could not write a correct tool call, so nothing was run."
_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}

Generate = Callable[[list[Message], bool], Awaitable[Reply]]
"""One generation over the messages; the flag says whether tools are offered."""
Run = Callable[[str, dict[str, Any]], Awaitable[ToolResult]]
Clip = Callable[[str], str]


@dataclass(slots=True)
class Loop:
    """How a loop went."""

    text: str = ""
    """The model's words in its last round."""
    said: str = ""
    """Everything it said, every round."""
    rounds: int = 0
    calls: int = 0
    bad: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stop: str = "end_turn"
    gave_up: bool = False


def problem(call: Call, specs: list[ToolSpec]) -> str:
    """Why `call` cannot run, in words for the model; empty when it can."""
    if call.problem:
        return call.problem
    spec = next((s for s in specs if s.name == call.name), None)
    if spec is None:
        names = ", ".join(s.name for s in specs) or "none"
        return f"there is no tool called {call.name!r}; the tools are: {names}"
    schema = spec.input_schema
    props: dict[str, Any] = schema.get("properties") or {}
    missing = [k for k in schema.get("required") or [] if k not in call.arguments]
    if missing:
        return f"{call.name} needs {', '.join(missing)}"
    if schema.get("additionalProperties") is False:
        extra = [k for k in call.arguments if k not in props]
        if extra:
            return f"{call.name} takes no {', '.join(extra)}; it takes {', '.join(props) or 'nothing'}"
    for key, value in call.arguments.items():
        wanted = (props.get(key) or {}).get("type")
        kinds = _TYPES.get(wanted) if isinstance(wanted, str) else None
        if kinds and (not isinstance(value, kinds) or (isinstance(value, bool) and bool not in kinds)):
            return f"{key} must be a {wanted}"
    return ""


async def run(
    generate: Generate,
    call: Run,
    specs: list[ToolSpec],
    messages: list[Message],
    *,
    max_rounds: int,
    clip: Clip = lambda text: text,
    on_call: Callable[[str, dict[str, Any], ToolResult], None] | None = None,
) -> Loop:
    """Run rounds until the model answers without a call. `messages` grows in place."""
    out = Loop()
    said: list[str] = []
    for round_no in range(max_rounds):
        offer = bool(specs) and round_no < max_rounds - 1
        reply = await generate(messages, offer)
        out.rounds += 1
        out.input_tokens += reply.input_tokens
        out.output_tokens += reply.output_tokens
        out.stop = reply.stop
        out.text = reply.text.strip()
        if out.text:
            said.append(out.text)
        if reply.stop in ("interrupted", "max_tokens") or not reply.calls or not offer:
            break
        good = [c for c in reply.calls if not problem(c, specs)]
        wrong = [(c, problem(c, specs)) for c in reply.calls if problem(c, specs)]
        messages.append(_assistant(reply, good, wrong))
        for c in good:
            result = await call(c.name, c.arguments)
            out.calls += 1
            if on_call is not None:
                on_call(c.name, c.arguments, result)
            content = clip(result.content) or "(no output)"
            messages.append(
                {"role": "tool", "tool_call_id": c.id, "name": c.name, "content": content if result.ok else f"Error: {content}"}
            )
        if wrong:
            out.bad += len(wrong)
            if out.bad > MAX_BAD:
                out.gave_up = True
                break
            messages.append({"role": "user", "content": _scolding(wrong)})
    out.said = "\n\n".join(said)
    return out


def _assistant(reply: Reply, good: list[Call], wrong: list[tuple[Call, str]]) -> Message:
    """The model's turn as it will be shown back: what it said, the calls that ran, and the
    text of those that did not (so it sees what it wrote)."""
    text = "\n".join([reply.text.strip(), *(c.raw for c, _ in wrong if c.raw)]).strip()
    message: Message = {"role": "assistant", "content": text}
    if good:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in good
        ]
    return message


def _scolding(wrong: list[tuple[Call, str]]) -> str:
    lines = [f"- {c.name or 'a call'}: {why}" for c, why in wrong]
    return (
        "Tool error: these calls were not run, because\n"
        + "\n".join(lines)
        + "\nWrite the call again in the right format with the right arguments, or answer without it."
    )
