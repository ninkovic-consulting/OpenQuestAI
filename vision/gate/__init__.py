"""Tools and the gate that decides whether they may run.

The composition root (`vision.app`) calls `make_tool_host`. Until it is
implemented it raises `NotImplementedError` and the daemon uses
`vision.testing.fakes.FakeToolHost` (no tools), publishing a notice.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Memory, ToolHost


def make_tool_host(config: Config, bus: Bus, memory: Memory) -> ToolHost:
    """Build the tool host for slice 1's five tools, with the gate in front.

    Must return an object satisfying `vision.core.interfaces.ToolHost`.
    Tiers come from `config.gate.tiers` (`config.gate.default_tier` for
    unlisted tools); `ask` waits up to `config.gate.timeout_s` for a
    `gate.decision` on `bus`. `remember` and `recall` use `memory`; every call
    is audited with `memory.audit`. Subscribe to the bus lazily (on the first
    `call`) or inside the running loop, not at construction time.
    """
    raise NotImplementedError("vision.gate.make_tool_host is not implemented yet")
