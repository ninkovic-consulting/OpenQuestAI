"""Tools and the gate that decides whether they may run.

The composition root (`vision.app`) calls `make_tool_host`. It does no I/O;
the gate subscribes to `gate.decision` only while a request is waiting.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Memory, ToolHost
from vision.gate.gate import ToolGate
from vision.gate.tools import build_tools


def make_tool_host(config: Config, bus: Bus, memory: Memory) -> ToolHost:
    """The gate in front of slice 1's five tools.

    The returned `ToolGate` also has `waiting` and `answer(text)` for settling
    a waiting request from a spoken or typed yes or no.
    """
    return ToolGate(config, bus, memory, build_tools(config, memory))
