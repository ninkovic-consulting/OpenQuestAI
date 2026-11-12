"""Schedules: checking them, and the next run for every kind, across daylight saving and month ends."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from vision.scheduler.cron import CronError, parse_cron
from vision.scheduler.schedule import ScheduleError, next_run, normalize
from vision.scheduler.words import describe, when

BERLIN = ZoneInfo("Europe/Berlin")  # clocks go forward 29 Mar 2026, back 25 Oct 2026
NEW_YORK = ZoneInfo("America/New_York")  # forward 8 Mar 2026, back 1 Nov 2026


def at(zone: ZoneInfo, *parts: int, fold: int = 0) -> float:
    return datetime(*parts, tzinfo=zone, fold=fold).timestamp()  # type: ignore[misc]


def local(ts: float | None, zone: ZoneInfo = BERLIN) -> str:
    assert ts is not None
    return datetime.fromtimestamp(ts, zone).strftime("%Y-%m-%d %H:%M %Z")


def nxt(schedule: dict[str, Any], after: float, zone: ZoneInfo = BERLIN, anchor: float = 0.0) -> float | None:
    return next_run(schedule, after, anchor, zone)


NOW = datetime(2026, 11, 12, 14, 3, 20, tzinfo=BERLIN)


# ------------------------------------------------------------------ checking


def test_normalize_every_kind() -> None:
    assert normalize({"kind": "once", "in_minutes": 20}, NOW) == {"kind": "once", "at": "2026-11-12T14:23:20"}
    assert normalize({"kind": "once", "at": "2026-11-13T09:00"}, NOW) == {"kind": "once", "at": "2026-11-13T09:00"}
    assert normalize({"kind": "daily", "time": "7:30"}, NOW) == {"kind": "daily", "time": "07:30"}
    assert normalize({"kind": "weekly", "days": ["Friday", "mon", "fri"], "time": "09:00"}, NOW) == {
        "kind": "weekly",
        "days": ["mon", "fri"],
        "time": "09:00",
    }
    assert normalize({"kind": "interval", "every": 2, "unit": "hours"}, NOW)["every"] == 2
    assert normalize({"kind": "cron", "expr": " 0  9 * * 1-5 "}, NOW) == {"kind": "cron", "expr": "0 9 * * 1-5"}


def test_an_at_with_an_offset_becomes_local_time() -> None:
    got = normalize({"kind": "once", "at": "2026-11-13T08:00:00+00:00"}, NOW)
    assert got == {"kind": "once", "at": "2026-11-13T09:00"}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"kind": "hourly"}, "kind must be one of"),
        ({"kind": "once", "at": "2026-11-12T14:00"}, "has already passed; it is now 2026-11-12T14:03:20"),
        ({"kind": "once", "at": "tomorrow"}, "local date and time"),
        ({"kind": "once"}, "either at"),
        ({"kind": "once", "in_minutes": 0.5}, "at least 1"),
        ({"kind": "daily", "time": "25:00"}, "HH:MM"),
        ({"kind": "weekly", "days": [], "time": "09:00"}, "needs days"),
        ({"kind": "weekly", "days": ["funday"], "time": "09:00"}, "is not a day"),
        ({"kind": "interval", "every": 30, "unit": "seconds"}, "minutes or hours"),
        ({"kind": "interval", "every": 0, "unit": "minutes"}, "1 or more"),
        ({"kind": "interval", "every": 1.5, "unit": "minutes"}, "whole number"),
        ({"kind": "interval", "every": 9000, "unit": "hours"}, "at most a year"),
        ({"kind": "cron", "expr": "* * * *"}, "five fields"),
        ({"kind": "cron", "expr": "0 9 31 2 *"}, "never comes round"),
        ({"kind": "daily", "time": "09:00", "days": ["mon"]}, "does not take days"),
    ],
)
def test_bad_schedules_are_refused_with_a_reason(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ScheduleError, match=message):
        normalize(raw, NOW)


def test_nothing_runs_more_than_once_a_minute() -> None:
    with pytest.raises(ScheduleError):
        normalize({"kind": "interval", "every": 0, "unit": "minutes"}, NOW)
    once_a_minute = normalize({"kind": "interval", "every": 1, "unit": "minutes"}, NOW)
    assert nxt(once_a_minute, 100.0, anchor=0.0) == 120.0
    # A cron line cannot name anything finer than a minute.
    every = parse_cron("* * * * *")
    assert len(every.minutes) == 60


# ------------------------------------------------------------------ once, daily, weekly


def test_once_runs_at_its_time_and_never_after() -> None:
    schedule = {"kind": "once", "at": "2026-11-13T09:00"}
    due = at(BERLIN, 2026, 11, 13, 9, 0)
    assert nxt(schedule, NOW.timestamp()) == due
    assert nxt(schedule, due) is None


def test_daily_today_or_tomorrow() -> None:
    schedule = {"kind": "daily", "time": "15:00"}
    assert local(nxt(schedule, NOW.timestamp())) == "2026-11-12 15:00 CET"
    early = {"kind": "daily", "time": "09:00"}
    assert local(nxt(early, NOW.timestamp())) == "2026-11-13 09:00 CET"
    # Exactly at the time, the next one is tomorrow's.
    assert local(nxt(early, at(BERLIN, 2026, 11, 13, 9, 0))) == "2026-11-14 09:00 CET"


def test_weekly_on_weekdays_skips_the_weekend() -> None:
    schedule = {"kind": "weekly", "days": ["mon", "tue", "wed", "thu", "fri"], "time": "09:00"}
    friday_noon = at(BERLIN, 2026, 11, 13, 12, 0)
    assert local(nxt(schedule, friday_noon)) == "2026-11-16 09:00 CET"


def test_daily_keeps_its_wall_time_across_both_changes() -> None:
    schedule = {"kind": "daily", "time": "07:30"}
    before_spring = at(BERLIN, 2026, 3, 28, 8, 0)
    assert local(nxt(schedule, before_spring)) == "2026-03-29 07:30 CEST"
    before_autumn = at(BERLIN, 2026, 10, 24, 8, 0)
    assert local(nxt(schedule, before_autumn)) == "2026-10-25 07:30 CET"
    # 23 and 25 hours apart in real time, the same on the clock.
    assert nxt(schedule, before_spring) - at(BERLIN, 2026, 3, 28, 7, 30) == 23 * 3600  # type: ignore[operator]
    assert nxt(schedule, before_autumn) - at(BERLIN, 2026, 10, 24, 7, 30) == 25 * 3600  # type: ignore[operator]


def test_a_time_the_clocks_skip_runs_after_the_gap() -> None:
    schedule = {"kind": "daily", "time": "02:30"}
    got = nxt(schedule, at(BERLIN, 2026, 3, 29, 0, 0))
    assert local(got) == "2026-03-29 03:30 CEST"
    # And the day after, back to 02:30.
    assert local(nxt(schedule, got)) == "2026-03-30 02:30 CEST"  # type: ignore[arg-type]


def test_a_time_that_happens_twice_runs_once() -> None:
    schedule = {"kind": "daily", "time": "02:30"}
    first = nxt(schedule, at(BERLIN, 2026, 10, 25, 0, 0))
    assert first == at(BERLIN, 2026, 10, 25, 2, 30, fold=0)
    assert local(first) == "2026-10-25 02:30 CEST"
    # Between the two 02:30s, the next run is the next day's.
    between = at(BERLIN, 2026, 10, 25, 2, 45, fold=0)
    assert local(nxt(schedule, between)) == "2026-10-26 02:30 CET"


def test_once_in_the_gap_and_in_another_zone() -> None:
    gap = {"kind": "once", "at": "2026-03-08T02:15"}
    assert local(nxt(gap, at(NEW_YORK, 2026, 3, 7, 0, 0), NEW_YORK), NEW_YORK) == "2026-03-08 03:15 EDT"


# ------------------------------------------------------------------ intervals


def test_interval_counts_real_time_from_its_anchor() -> None:
    schedule = {"kind": "interval", "every": 20, "unit": "minutes"}
    anchor = at(BERLIN, 2026, 11, 12, 14, 0)
    assert nxt(schedule, anchor, anchor=anchor) == anchor + 1200
    assert nxt(schedule, anchor + 1200, anchor=anchor) == anchor + 2400
    # Missed several: the next is the first one still ahead.
    assert nxt(schedule, anchor + 3 * 3600 + 5, anchor=anchor) == anchor + 3 * 3600 + 1200


def test_interval_stays_two_hours_apart_when_the_clocks_change() -> None:
    schedule = {"kind": "interval", "every": 2, "unit": "hours"}
    anchor = at(BERLIN, 2026, 10, 25, 1, 0)
    got = nxt(schedule, anchor, anchor=anchor)
    assert got == anchor + 7200
    assert local(got) == "2026-10-25 02:00 CET"


# ------------------------------------------------------------------ cron


def test_cron_weekdays_and_steps() -> None:
    weekdays = {"kind": "cron", "expr": "0 9 * * 1-5"}
    saturday = at(BERLIN, 2026, 11, 14, 10, 0)
    assert local(nxt(weekdays, saturday)) == "2026-11-16 09:00 CET"
    quarters = {"kind": "cron", "expr": "*/15 8-18 * * *"}
    assert local(nxt(quarters, at(BERLIN, 2026, 11, 12, 14, 3))) == "2026-11-12 14:15 CET"
    assert local(nxt(quarters, at(BERLIN, 2026, 11, 12, 18, 45))) == "2026-11-13 08:00 CET"


def test_cron_month_ends_and_leap_days() -> None:
    thirty_first = {"kind": "cron", "expr": "0 12 31 * *"}
    assert local(nxt(thirty_first, at(BERLIN, 2026, 1, 31, 13, 0))) == "2026-03-31 12:00 CEST"
    assert local(nxt(thirty_first, at(BERLIN, 2026, 4, 1, 0, 0))) == "2026-05-31 12:00 CEST"
    leap = {"kind": "cron", "expr": "0 0 29 feb *"}
    assert local(nxt(leap, at(BERLIN, 2026, 11, 12, 0, 0))) == "2028-02-29 00:00 CET"
    first = {"kind": "cron", "expr": "15 9 1 * *"}
    assert local(nxt(first, at(BERLIN, 2026, 12, 31, 23, 0))) == "2027-01-01 09:15 CET"


def test_cron_day_of_month_or_day_of_week() -> None:
    # Classic cron: the 13th, or any Friday.
    either = {"kind": "cron", "expr": "0 8 13 * fri"}
    assert local(nxt(either, at(BERLIN, 2026, 11, 12, 9, 0))) == "2026-11-13 08:00 CET"
    assert local(nxt(either, at(BERLIN, 2026, 11, 13, 9, 0))) == "2026-11-20 08:00 CET"
    sunday_as_seven = {"kind": "cron", "expr": "0 8 * * 7"}
    assert local(nxt(sunday_as_seven, NOW.timestamp())) == "2026-11-15 08:00 CET"


def test_cron_across_daylight_saving() -> None:
    hourly = {"kind": "cron", "expr": "30 * * * *"}
    spring = nxt(hourly, at(BERLIN, 2026, 3, 29, 1, 45))
    assert local(spring) == "2026-03-29 03:30 CEST"
    autumn = nxt(hourly, at(BERLIN, 2026, 10, 25, 1, 45))
    assert local(autumn) == "2026-10-25 02:30 CEST"


@pytest.mark.parametrize("expr", ["60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 8", "5-1 * * * *", "*/0 * * * *", "x * * * *"])
def test_cron_refuses_what_it_cannot_read(expr: str) -> None:
    with pytest.raises(CronError):
        parse_cron(expr)


# ------------------------------------------------------------------ words


def test_schedules_in_words() -> None:
    assert describe({"kind": "once", "at": "2026-11-13T09:00"}) == "once on Fri 13 Nov 2026 at 09:00"
    assert describe({"kind": "daily", "time": "07:30"}) == "every day at 07:30"
    weekdays = ["mon", "tue", "wed", "thu", "fri"]
    assert describe({"kind": "weekly", "days": weekdays, "time": "09:00"}) == "every weekday at 09:00"
    assert describe({"kind": "weekly", "days": ["mon", "wed", "fri"], "time": "18:00"}) == "every Mon, Wed and Fri at 18:00"
    assert describe({"kind": "interval", "every": 1, "unit": "hours"}) == "every hour"
    assert describe({"kind": "interval", "every": 20, "unit": "minutes"}) == "every 20 minutes"
    assert describe({"kind": "cron", "expr": "0 9 * * 1-5"}) == "on the cron line 0 9 * * 1-5"
    assert when(at(BERLIN, 2026, 11, 13, 9, 0), BERLIN) == "Fri 13 Nov 2026 at 09:00"
