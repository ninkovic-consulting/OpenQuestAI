"""Brains: Claude, the local model, the router, and the budget.

The composition root (`vision.app`) calls these two factories. Until they are
implemented they raise `NotImplementedError` and the daemon uses the fakes
from `vision.testing.fakes`, publishing a notice that says so.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Brain, Budget, Memory, ToolHost


def make_brain(config: Config, bus: Bus, tools: ToolHost, memory: Memory, budget: Budget) -> Brain:
    """Build the brain the session talks to: the router over Claude and the local model.

    Must return an object satisfying `vision.core.interfaces.Brain` whose
    `name` reports the backend currently answering. Must not do network I/O
    here; do that in `Brain.start()`. A missing API key is not an error: the
    router runs on the local model and publishes a notice asking for
    `vision auth` (key lookup: `vision.core.secrets.get_api_key`).
    """
    raise NotImplementedError("vision.brains.make_brain is not implemented yet")


def make_budget(config: Config, bus: Bus) -> Budget:
    """Build the monthly spend tracker.

    Must return an object satisfying `vision.core.interfaces.Budget`, priced
    from `config.budget.prices`, capped at `config.budget.monthly_cap_usd`,
    persisted under `config.paths.home`. Called before `make_brain`.
    """
    raise NotImplementedError("vision.brains.make_budget is not implemented yet")
