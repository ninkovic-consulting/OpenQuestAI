"""The assistant's awareness of itself and its surroundings, read-only.

- `Awareness.summary()`: a few current lines (who runs which room, and what
  cannot be done yet) that the session adds to the user's message, never to
  the cached system prompt, whenever they change.
- `build_tools(awareness)`: `house_overview`, `room_details` and
  `assistant_status`, free tier, offered behind the gate.
- `limits`: the one place that says who can take work and what each
  resident can and cannot do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vision.aware.house_view import HouseView, summary
from vision.aware.personas import Personas
from vision.aware.tools import NAMES, build_tools

if TYPE_CHECKING:
    from vision.app import Daemon


class Awareness:
    def __init__(self, daemon: Daemon) -> None:
        self.daemon = daemon
        self._personas = Personas(daemon.config.paths.house)

    def view(self) -> HouseView:
        d = self.daemon
        states = d.board.agent_states()
        return HouseView(
            d.components.house.plan(),
            self._personas,
            d.snapshot.state,
            jobs=d.board.open_jobs(),
            waiting=frozenset(a for a, s in states.items() if s["state"] == "waiting"),
            project_tools=d.residents.has_project_tools,
            offline=d.config.brain.offline,
            local_model=d.local.model,
            local_tools=d.local.known_tools(),
        )

    def summary(self) -> str:
        return summary(self.view())


__all__ = ["NAMES", "Awareness", "build_tools"]
