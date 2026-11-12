"""Schedules and times in plain words, for notices and for the model."""

from __future__ import annotations

from datetime import datetime, tzinfo

from vision.scheduler.schedule import WEEK, Schedule

_DAY_NAMES = dict(zip(WEEK, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), strict=True))


def describe(schedule: Schedule) -> str:
    """"every weekday at 09:00", "once on Fri 13 Nov 2026 at 09:00", "every 20 minutes"."""
    match schedule["kind"]:
        case "once":
            at = datetime.fromisoformat(schedule["at"])
            return f"once on {at:%a} {at.day} {at:%b %Y} at {at:%H:%M}"
        case "daily":
            return f"every day at {schedule['time']}"
        case "weekly":
            return f"{_days(schedule['days'])} at {schedule['time']}"
        case "interval":
            every, unit = schedule["every"], schedule["unit"]
            return f"every {unit[:-1]}" if every == 1 else f"every {every} {unit}"
        case _:
            return f"on the cron line {schedule['expr']}"


def _days(days: list[str]) -> str:
    if days == list(WEEK):
        return "every day"
    if days == list(WEEK[:5]):
        return "every weekday"
    if days == list(WEEK[5:]):
        return "every weekend day"
    names = [_DAY_NAMES[d] for d in days]
    listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"every {listed}"


def when(ts: float, zone: tzinfo) -> str:
    """"Fri 13 Nov 2026 at 09:00", in the given zone."""
    moment = datetime.fromtimestamp(ts, zone)
    return f"{moment:%a} {moment.day} {moment:%b %Y} at {moment:%H:%M}"
