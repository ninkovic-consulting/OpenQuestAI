"""Five-field cron lines: minute, hour, day of month, month, day of week.

Each field takes `*`, numbers, ranges (`1-5`), steps (`*/15`, `8-18/2`) and
lists (`1,15`); months and days also take names (`jan`, `mon`). Day of week
runs 0 to 7, where both 0 and 7 are Sunday. As in classic cron, when both the
day of month and the day of week are restricted, a day matching either one
counts. Pure: no clock, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_PART = re.compile(r"^(\*|[a-z0-9]+(?:-[a-z0-9]+)?)(?:/(\d+))?$")


class CronError(ValueError):
    """A cron line that cannot be read; the message is for people."""


@dataclass(frozen=True, slots=True)
class Cron:
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    """0 is Sunday."""
    any_day: bool
    any_weekday: bool

    def day_matches(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        by_day = day.day in self.days
        by_weekday = (day.weekday() + 1) % 7 in self.weekdays
        if self.any_day and self.any_weekday:
            return True
        if self.any_day:
            return by_weekday
        if self.any_weekday:
            return by_day
        return by_day or by_weekday


def parse_cron(line: str) -> Cron:
    fields = line.lower().split()
    if len(fields) != 5:
        raise CronError(
            "A cron line has five fields: minute, hour, day of month, month and day of week, "
            'for example "30 7 * * 1-5".'
        )
    minute, hour, day, month, weekday = fields
    weekdays = _field(weekday, 0, 7, DAYS, "day of week")
    return Cron(
        minutes=tuple(sorted(_field(minute, 0, 59, (), "minute"))),
        hours=tuple(sorted(_field(hour, 0, 23, (), "hour"))),
        days=frozenset(_field(day, 1, 31, (), "day of month")),
        months=frozenset(_field(month, 1, 12, MONTHS, "month", first_name=1)),
        weekdays=frozenset(d % 7 for d in weekdays),
        any_day=day == "*",
        any_weekday=weekday == "*",
    )


def _field(
    text: str, low: int, high: int, names: tuple[str, ...], what: str, *, first_name: int = 0
) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        found = _PART.match(part)
        if found is None:
            raise CronError(f"The {what} field {text!r} is not something cron understands.")
        span, step_text = found.groups()
        step = int(step_text) if step_text else 1
        if step < 1:
            raise CronError(f"The step in the {what} field must be 1 or more.")
        if span == "*":
            start, end = low, high
        else:
            start_text, _, end_text = span.partition("-")
            start = _value(start_text, low, high, names, what, first_name)
            end = _value(end_text, low, high, names, what, first_name) if end_text else start
            if step_text and not end_text:
                end = high
            if end < start:
                raise CronError(f"The range {span!r} in the {what} field runs backwards.")
        values.update(range(start, end + 1, step))
    return values


def _value(
    text: str, low: int, high: int, names: tuple[str, ...], what: str, first_name: int
) -> int:
    if text in names:
        return names.index(text) + first_name
    if not text.isdigit():
        raise CronError(f"{text!r} is not a valid {what}.")
    number = int(text)
    if not low <= number <= high:
        raise CronError(f"The {what} must be from {low} to {high}; {number} is not.")
    return number
