"""The Mac's local time zone, and the current local time in words.

Schedules are kept in local wall-clock time and turned into instants with the
real zone rules, so daylight-saving changes come out right. The zone is read
from `TZ` when set, else from the `/etc/localtime` link macOS keeps; when
neither names a zone, the current fixed offset is used.
"""

from __future__ import annotations

import os
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCALTIME = Path("/etc/localtime")


def local_zone() -> tzinfo:
    for key in (os.environ.get("TZ", "").lstrip(":"), _linked_key()):
        if key:
            try:
                return ZoneInfo(key)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone


def _linked_key() -> str:
    try:
        target = str(LOCALTIME.resolve())
    except OSError:
        return ""
    _, found, key = target.partition("zoneinfo/")
    return key if found else ""


def zone_name(zone: tzinfo) -> str:
    return zone.key if isinstance(zone, ZoneInfo) else (datetime.now(zone).tzname() or "local time")


def now_words(now: datetime) -> str:
    """"Thursday 12 November 2026, 14:03 (Europe/Berlin)" for an aware local time."""
    assert now.tzinfo is not None
    return f"{now:%A} {now.day} {now:%B %Y, %H:%M} ({zone_name(now.tzinfo)})"
