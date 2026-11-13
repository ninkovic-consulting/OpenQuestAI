"""Brains: Claude, the local model, the router, and the budget.

The composition root (`vision.app`) calls these factories. None does I/O;
the brain loads its key and clients in `Brain.start()`, the budget reads its
file on first use, and the local engine loads its model when offline mode is
on (from the local brain's start) or on the first generation. The engine is
one per daemon: the host's local brain and the
residents' local jobs share it, so one generation runs at a time.
"""

from __future__ import annotations

from vision.brains.budget import MonthlyBudget
from vision.brains.claude import ClaudeBrain
from vision.brains.engine import LocalEngine
from vision.brains.local import SEES_IMAGES, LocalBrain
from vision.brains.router import Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BrainMode, BrainName
from vision.core.interfaces import Brain, Budget, Memory, ToolHost


def make_engine(config: Config, bus: Bus) -> LocalEngine:
    """The local model (`[brain] local_backend`, `local_model`), shared by host and residents."""
    return LocalEngine(config, bus)


def make_brain(
    config: Config, bus: Bus, tools: ToolHost, memory: Memory, budget: Budget, engine: LocalEngine
) -> Brain:
    """The router over Claude and the local model, which gets the same tools."""
    claude = ClaudeBrain(config, tools, memory, budget)
    router = Router(config, bus, claude, LocalBrain(config, memory, engine, tools), budget)
    engine.on_change = lambda: bus.publish(mode(config, router.name, engine))
    return router


def make_budget(config: Config, bus: Bus) -> Budget:
    """The monthly spend tracker, persisted in `<home>/budget.json`."""
    return MonthlyBudget(config, bus)


def mode(config: Config, answering: BrainName, engine: LocalEngine) -> BrainMode:
    """Offline or not, who answers the host now, and the local model: the `brain.mode` event,
    and `mode` in `GET /api/state`."""
    status = engine.status()
    return BrainMode(
        offline=config.brain.offline,
        answering=answering,
        local_backend=engine.backend,
        local_model=engine.model,
        local_tools=engine.known_tools(),
        local_images=SEES_IMAGES,
        local_state=status.state,
        local_bytes=status.weights_bytes,
        local_cache_bytes=status.cache_bytes,
        local_reading=status.reading,
        local_problem=status.problem,
    )
