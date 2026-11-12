"""Brains: Claude, the local model, the router, and the budget.

The composition root (`vision.app`) calls these two factories. Neither does
I/O; the brain loads its key and clients in `Brain.start()` and the budget
reads its file on first use.
"""

from __future__ import annotations

from vision.brains.budget import MonthlyBudget
from vision.brains.local import LocalBrain
from vision.brains.router import Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Brain, Budget, Memory, ToolHost


def make_brain(config: Config, bus: Bus, tools: ToolHost, memory: Memory, budget: Budget) -> Brain:
    """The router over Claude and the local model.

    Without the `brains` extra (no Anthropic SDK) the router runs on the local
    model alone and says so in a notice when it starts.
    """
    try:
        from vision.brains.claude import ClaudeBrain
    except ImportError:
        claude = None
    else:
        claude = ClaudeBrain(config, tools, memory, budget)
    return Router(config, bus, claude, LocalBrain(config, memory), budget)


def make_budget(config: Config, bus: Bus) -> Budget:
    """The monthly spend tracker, persisted in `<home>/budget.json`."""
    return MonthlyBudget(config, bus)
