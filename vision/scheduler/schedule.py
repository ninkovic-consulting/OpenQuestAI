"""Schedules: checking what people (or the model) send, and working out the next run.

A schedule is a small JSON object, stored as `normalize` returns it:

| kind       | fields                                         | example                         |
|------------|------------------------------------------------|---------------------------------|
| `once`     | `at`: local date and time                      | `"2026-11-13T09:00"`            |
| `daily`    | `time`: `HH:MM`                                | `"07:30"`                       |
| `weekly`   | `days` (`mon` to `sun`), `time`                | `["mon", "fri"]`, `"09:00"`     |
| `interval` | `every` (whole number), `unit` (minutes/hours) | `20`, `"minutes"`               |
| `cron`     | `expr`: five fields                            | `"15 9 1 * *"`                  |

A `once` may be sent with `in_minutes` instead of `at`; it is stored as `at`.

Times are wall-clock times in the Mac's zone and become instants with its
rules, so a daily run stays at 07:30 across daylight-saving changes. A time
that does not exist on the day the clocks go forward moves forward by the
gap (02:30 runs at 03:30); a time that happens twice when they go back runs
once, at the first. An interval counts real time from its anchor, so "every
2 hours" stays two hours apart through a change.

Pure: the caller passes the time and the zone.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from vision.scheduler.cron import CronError, parse_cron

KINDS = ("once", "daily", "weekly", "interval", "cron")
WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
"""In Python's weekday order, Monday first."""
UNITS = {"minutes": 60, "hours": 3600}
MAX_PERIOD_S = 366 * 86400
MAX_AHEAD_DAYS = 5 * 366
CRON_SEARCH_DAYS = 8 * 366
"""Long enough for a cron line that only fires on 29 February."""
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_FULL_DAYS = {d: d[:3] for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}

Schedule = dict[str, Any]


class ScheduleError(ValueError):
    """A schedule that cannot be used; the message is for people."""


# ------------------------------------------------------------------ checking


def normalize(raw: Any, now: datetime) -> Schedule:
    """The schedule to store, or `ScheduleError`. `now` is the aware local time."""
    if not isinstance(raw, dict):
        raise ScheduleError("The schedule must be an object with a kind.")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ScheduleError(f"The schedule's kind must be one of {', '.join(KINDS)}.")
    allowed = {
        "once": {"at", "in_minutes"},
        "daily": {"time"},
        "weekly": {"days", "time"},
        "interval": {"every", "unit"},
        "cron": {"expr"},
    }[kind]
    extra = set(raw) - allowed - {"kind"}
    if extra:
        raise ScheduleError(f"A {kind} schedule does not take {', '.join(sorted(extra))}.")
    match kind:
        case "once":
            return {"kind": "once", "at": _once_at(raw, now)}
        case "daily":
            return {"kind": "daily", "time": _hhmm(raw.get("time"))}
        case "weekly":
            return {"kind": "weekly", "days": _days(raw.get("days")), "time": _hhmm(raw.get("time"))}
        case "interval":
            every, unit = _interval(raw.get("every"), raw.get("unit"))
            return {"kind": "interval", "every": every, "unit": unit}
        case _:
            expr = raw.get("expr")
            if not isinstance(expr, str):
                raise ScheduleError("A cron schedule needs expr, five fields such as \"0 9 * * 1-5\".")
            expr = " ".join(expr.split())
            try:
                cron = parse_cron(expr)
            except CronError as exc:
                raise ScheduleError(str(exc)) from None
            if not any(cron.day_matches(now.date() + timedelta(d)) for d in range(CRON_SEARCH_DAYS)):
                raise ScheduleError(f"The cron line {expr!r} never comes round.")
            return {"kind": "cron", "expr": expr}


def _once_at(raw: dict[str, Any], now: datetime) -> str:
    zone = now.tzinfo
    assert zone is not None
    if ("at" in raw) == ("in_minutes" in raw):
        raise ScheduleError("A once schedule needs either at (a local date and time) or in_minutes.")
    if "in_minutes" in raw:
        minutes = raw["in_minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not math.isfinite(minutes):
            raise ScheduleError("in_minutes must be a number of minutes.")
        if not 1 <= minutes <= MAX_AHEAD_DAYS * 1440:
            raise ScheduleError("in_minutes must be at least 1, and at most about five years.")
        when = (now + timedelta(minutes=minutes)).replace(microsecond=0)
    else:
        text = raw["at"]
        try:
            parsed = datetime.fromisoformat(text) if isinstance(text, str) else None
        except ValueError:
            parsed = None
        if parsed is None:
            raise ScheduleError('at must be a local date and time such as "2026-11-13T09:00".')
        when = parsed.astimezone(zone) if parsed.tzinfo else resolve(parsed, zone)
        when = when.replace(microsecond=0)
        if when <= now:
            raise ScheduleError(f"{wall(when)} has already passed; it is now {wall(now)}.")
        if when - now > timedelta(days=MAX_AHEAD_DAYS):
            raise ScheduleError("That is more than five years away.")
    return wall(when.astimezone(zone))


def wall(moment: datetime) -> str:
    """`2026-11-13T09:00`, with seconds only when they are not zero."""
    spec = "%Y-%m-%dT%H:%M:%S" if moment.second else "%Y-%m-%dT%H:%M"
    return moment.strftime(spec)


def _hhmm(value: Any) -> str:
    found = _HHMM.match(value.strip()) if isinstance(value, str) else None
    if found is None:
        raise ScheduleError('The time must be HH:MM on the 24-hour clock, such as "07:30".')
    return f"{int(found.group(1)):02d}:{found.group(2)}"


def _days(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ScheduleError("A weekly schedule needs days, such as [\"mon\", \"wed\"].")
    picked: set[str] = set()
    for item in value:
        name = item.strip().lower() if isinstance(item, str) else ""
        name = _FULL_DAYS.get(name, name)
        if name not in WEEK:
            raise ScheduleError(f"{item!r} is not a day; use mon, tue, wed, thu, fri, sat or sun.")
        picked.add(name)
    return [d for d in WEEK if d in picked]


def _interval(every: Any, unit: Any) -> tuple[int, str]:
    if unit not in UNITS:
        raise ScheduleError("An interval's unit must be minutes or hours.")
    if isinstance(every, bool) or not isinstance(every, int) or every < 1:
        raise ScheduleError("An interval's every must be a whole number, 1 or more.")
    if every * UNITS[unit] > MAX_PERIOD_S:
        raise ScheduleError("An interval can be at most a year.")
    return every, unit


# ------------------------------------------------------------------ the next run


def resolve(local: datetime, zone: tzinfo) -> datetime:
    """A naive wall-clock time as an instant in `zone`, by the rules in the module notes."""
    return local.replace(tzinfo=zone, fold=0)


def period_s(schedule: Schedule) -> int:
    return int(schedule["every"]) * UNITS[schedule["unit"]]


def next_run(schedule: Schedule, after: float, anchor: float, zone: tzinfo) -> float | None:
    """The first run strictly after `after` (Unix seconds), or None when there is none.

    `anchor` is when an interval started counting (it runs at anchor + k
    periods, k of 1 or more); other kinds ignore it.
    """
    kind = schedule["kind"]
    if kind == "interval":
        period = period_s(schedule)
        steps = max(1, math.floor((after - anchor) / period) + 1)
        return anchor + steps * period
    if kind == "once":
        at = resolve(datetime.fromisoformat(schedule["at"]), zone).timestamp()
        return at if at > after else None
    start = datetime.fromtimestamp(after, zone).date()
    if kind == "cron":
        return _next_cron(schedule["expr"], start, after, zone)
    hour, minute = (int(p) for p in schedule["time"].split(":"))
    days = set(range(7)) if kind == "daily" else {WEEK.index(d) for d in schedule["days"]}
    for offset in range(8):
        day = start + timedelta(days=offset)
        if day.weekday() in days:
            moment = resolve(datetime.combine(day, time(hour, minute)), zone).timestamp()
            if moment > after:
                return moment
    return None


def _next_cron(expr: str, start: date, after: float, zone: tzinfo) -> float | None:
    cron = parse_cron(expr)
    for offset in range(CRON_SEARCH_DAYS):
        day = start + timedelta(days=offset)
        if not cron.day_matches(day):
            continue
        found = [
            moment
            for hour in cron.hours
            for minute in cron.minutes
            if (moment := resolve(datetime.combine(day, time(hour, minute)), zone).timestamp()) > after
        ]
        if found:
            return min(found)
    return None
