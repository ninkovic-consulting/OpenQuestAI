"""The house: a configurable layout of rooms and residents.

The composition root (`vision.app`) calls `make_house`. Until it is
implemented it raises `NotImplementedError` and the daemon uses
`vision.testing.fakes.FakeHouse` (one room, no editing routes), publishing a
notice.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import House


def make_house(config: Config, bus: Bus) -> House:
    """Build the house from `config.paths.house_file` and `config.agents`.

    Must return an object satisfying `vision.core.interfaces.House`. Its
    `router`, if any, is mounted under `/api/house` with the core's token and
    Origin checks already applied. Publish `house.changed` on `bus` after
    every change to the plan.
    """
    raise NotImplementedError("vision.house.make_house is not implemented yet")
