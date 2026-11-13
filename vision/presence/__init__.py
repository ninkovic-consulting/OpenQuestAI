"""Presence: whether the owner is at the Mac, which decides what goes to the phone.

    presence = make_presence(config, bus)   # no I/O here
    task = asyncio.create_task(presence.run())
    presence.check()                         # a fresh `Seen`

`reader.MacReader` reads the idle time, the lock and the display's sleep
through CoreGraphics, with no permission; `watch.Presence` turns readings
into away or present and publishes `presence` when that changes. Tests
replace `default_reader` with a fake.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.presence.reader import MacReader, Reader, Reading
from vision.presence.watch import Presence, Seen


def default_reader() -> Reader:
    return MacReader()


def make_presence(config: Config, bus: Bus) -> Presence:
    return Presence(config, bus, default_reader())


__all__ = ["Presence", "Reader", "Reading", "Seen", "default_reader", "make_presence"]
