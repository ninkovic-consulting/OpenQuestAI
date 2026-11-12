"""The assistant's tools for automations: create, list, update, pause, resume, run now, delete.

They are gate tools like the five of slice 1, so the gate decides each call
and audits it. Every change publishes a `notice` saying what was scheduled,
changed or removed. During an automation's own run the gate refuses every
tool but the list: an automation cannot create, change or delete automations.

The model learns the local date and time from the message (see
`vision.core.turns`) or from the list, whose first line is the time now.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from vision.core.events import Notice
from vision.core.localtime import now_words
from vision.core.interfaces import ToolSpec
from vision.gate.tools import Tool, ToolFailure
from vision.scheduler.model import INSTRUCTION_MAX, MAX_AUTOMATIONS, NAME_MAX, Automation
from vision.scheduler.schedule import KINDS, WEEK
from vision.scheduler.service import AutomationError, Automations, NotFound
from vision.scheduler.words import describe, when

UNATTENDED = "An automation cannot create, change or delete automations, so this was not done."

SCHEDULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "When it runs, in the Mac's local time.",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "at": {"type": "string", "description": "once: local date and time, YYYY-MM-DDTHH:MM."},
        "in_minutes": {"type": "number", "description": "once: minutes from now, instead of at."},
        "time": {"type": "string", "description": "daily and weekly: HH:MM, 24-hour clock."},
        "days": {"type": "array", "items": {"type": "string", "enum": list(WEEK)}},
        "every": {"type": "integer", "minimum": 1, "description": "interval: how many units."},
        "unit": {"type": "string", "enum": ["minutes", "hours"]},
        "expr": {"type": "string", "description": "cron: minute hour day-of-month month day-of-week."},
    },
    "required": ["kind"],
    "additionalProperties": False,
}

REF = {"type": "string", "description": "The automation's id, or its exact name."}

CREATE = (
    "Schedule an automation: an instruction you will carry out by yourself at set times, "
    "perhaps with nobody watching, such as a reminder, a briefing or a regular check. Use it "
    "when the user asks to be reminded of something, or for something to happen later, at a "
    "time, or regularly. Times are the Mac's local time. Turn their words into schedule:\n"
    '- "in twenty minutes" -> {"kind": "once", "in_minutes": 20}\n'
    '- "tomorrow at nine" -> {"kind": "once", "at": "<tomorrow\'s date>T09:00"}\n'
    '- "every day at 7:30" -> {"kind": "daily", "time": "07:30"}\n'
    '- "every weekday at nine" -> {"kind": "weekly", "days": ["mon", "tue", "wed", "thu", '
    '"fri"], "time": "09:00"}\n'
    '- "every two hours" -> {"kind": "interval", "every": 2, "unit": "hours"}\n'
    '- anything else, such as "at 9:15 on the first of each month" -> {"kind": "cron", '
    '"expr": "15 9 1 * *"}\n'
    "The user's message carries the local date and time when it mentions a time; if you do "
    "not have it, call list_automations first, whose first line is the time now. Write the "
    "instruction as what to do when it runs, addressed to yourself, e.g. \"Remind the user "
    "to stretch.\" Nothing runs more often than once a minute, and there can be at most "
    f"{MAX_AUTOMATIONS}. Afterwards tell the user, in a few words, what you scheduled and when."
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def build_tools(automations: Automations) -> list[Tool]:
    """The seven tools, in a fixed order (stable for prompt caching)."""

    def notice(text: str) -> None:
        automations.bus.publish(Notice(level="info", text=text))

    def find(args: dict[str, Any]) -> Automation:
        ref = args.get("automation")
        if not isinstance(ref, str) or not ref.strip():
            raise ToolFailure("Say which automation, by its id or its name.")
        try:
            return automations.find(ref.strip())
        except NotFound as exc:
            raise ToolFailure(f"{exc} Call list_automations to see them.") from None

    def line(a: Automation) -> str:
        zone = automations.zone()
        if a.paused:
            state = "paused"
        elif a.finished or a.next_run is None:
            state = "finished"
        else:
            state = f"next {when(a.next_run, zone)}"
        last = a.results[-1] if a.results else None
        outcome = f"; last run {last.status}: {last.reply[:80]}" if last else ""
        speech = "spoken" if a.speak else "shown only"
        return (
            f'- {a.id} "{a.name}": {describe(a.schedule)}, {state}, {speech}. '
            f"Does: {a.instruction[:120]}{outcome}"
        )

    async def changing(make: Callable[[], Awaitable[Automation]]) -> Automation:
        try:
            return await make()
        except (AutomationError, NotFound) as exc:
            raise ToolFailure(str(exc)) from None

    async def create(args: dict[str, Any]) -> str:
        a = await changing(lambda: automations.create(_fields(args)))
        notice(f'Scheduled "{a.name}": {describe(a.schedule)}.')
        return f"Scheduled. {line(a)}"

    async def list_all(args: dict[str, Any]) -> str:
        head = f"Local time now: {now_words(automations.now_local())}."
        found = automations.all()
        if not found:
            return f"{head}\nThere are no automations."
        return "\n".join([head, f"{len(found)} of at most {MAX_AUTOMATIONS}:", *map(line, found)])

    async def update(args: dict[str, Any]) -> str:
        target = find(args)
        a = await changing(lambda: automations.update(target.id, _fields(args)))
        notice(f'Changed "{a.name}": {describe(a.schedule)}.')
        return f"Changed. {line(a)}"

    def pauser(paused: bool) -> Callable[[dict[str, Any]], Awaitable[str]]:
        async def run(args: dict[str, Any]) -> str:
            target = find(args)
            a = await changing(lambda: automations.update(target.id, {"paused": paused}))
            notice(f'{"Paused" if paused else "Resumed"} "{a.name}".')
            return f"{'Paused' if paused else 'Resumed'}. {line(a)}"

        return run

    async def run_now(args: dict[str, Any]) -> str:
        a = automations.request_run(find(args).id)
        notice(f'Running "{a.name}" now.')
        return f'"{a.name}" will run as soon as this conversation turn is over.'

    async def delete(args: dict[str, Any]) -> str:
        target = find(args)
        a = await changing(lambda: automations.delete(target.id))
        notice(f'Removed "{a.name}" ({describe(a.schedule)}).')
        return f'Deleted "{a.name}".'

    def describe_ref(args: dict[str, Any]) -> str:
        ref = args.get("automation")
        try:
            a = automations.find(ref) if isinstance(ref, str) else None
        except NotFound:
            a = None
        return f'"{a.name}", {describe(a.schedule)}' if a else str(ref)

    name = {"type": "string", "description": f"A short, unique name, at most {NAME_MAX} characters."}
    instruction = {
        "type": "string",
        "description": f"What to do when it runs, at most {INSTRUCTION_MAX} characters.",
    }
    speak = {
        "type": "boolean",
        "description": "True (the default) to say the result aloud; false to only show it.",
    }
    ref_only = _schema({"automation": REF}, ["automation"])
    return [
        Tool(
            ToolSpec(
                "create_automation",
                CREATE,
                _schema(
                    {"name": name, "instruction": instruction, "schedule": SCHEDULE_SCHEMA, "speak": speak},
                    ["name", "instruction", "schedule"],
                ),
            ),
            create,
            "Schedule an automation",
            "name",
            unattended_refusal=UNATTENDED,
        ),
        Tool(
            ToolSpec(
                "list_automations",
                "List the automations with their schedules, next runs and last results, after "
                "a first line with the current local date and time. Use it when the user asks "
                "what is scheduled, before changing one whose id you do not know, or to learn "
                "the time now.",
                _schema({}, []),
            ),
            list_all,
            "List automations",
            "",
        ),
        Tool(
            ToolSpec(
                "update_automation",
                "Change an automation's name, instruction, schedule or whether its result is "
                "spoken. Send only what changes; a schedule takes the same shapes as in "
                "create_automation, and a new schedule starts counting from now.",
                _schema(
                    {"automation": REF, "name": name, "instruction": instruction,
                     "schedule": SCHEDULE_SCHEMA, "speak": speak},
                    ["automation"],
                ),
            ),
            update,
            "Change an automation",
            "automation",
            describe_ref,
            UNATTENDED,
        ),
        Tool(
            ToolSpec(
                "pause_automation",
                "Pause an automation so it does not run until it is resumed.",
                ref_only,
            ),
            pauser(True),
            "Pause an automation",
            "automation",
            describe_ref,
            UNATTENDED,
        ),
        Tool(
            ToolSpec(
                "resume_automation",
                "Resume a paused automation; it runs again from its next time after now.",
                ref_only,
            ),
            pauser(False),
            "Resume an automation",
            "automation",
            describe_ref,
            UNATTENDED,
        ),
        Tool(
            ToolSpec(
                "run_automation",
                "Run an automation once, now, outside its schedule. It starts when the current "
                "turn is over. Its schedule does not change.",
                ref_only,
            ),
            run_now,
            "Run an automation now",
            "automation",
            describe_ref,
            UNATTENDED,
        ),
        Tool(
            ToolSpec(
                "delete_automation",
                "Delete an automation and its results for good. Use it only when the user asks "
                "to remove, delete or cancel one; to stop one for a while, pause it instead.",
                ref_only,
            ),
            delete,
            "Delete an automation",
            "automation",
            describe_ref,
            UNATTENDED,
        ),
    ]


def _fields(args: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k in ("name", "instruction", "schedule", "speak")}
