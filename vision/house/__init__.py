"""The house: a grid of rooms, the agents who run them, and the routes to edit it.

`house/default.toml` in the repo is the default house. The user's file at
`config.paths.house_file` overrides it and is created from it on first use.
`[agents.<id>]` tables in config.toml override both for agents. The agent
personas in the repo's `house/agents/` are copied into the memory vault by
`seed_personas` before memory starts, so the host persona the user edits is
`$VISION_HOME/house/agents/host.md`.
"""

from __future__ import annotations

from typing import NamedTuple

from vision.core.bus import Bus
from vision.core.config import Config
from vision.house import store
from vision.house.house import GridHouse
from vision.house.model import HouseError, UnknownRoom
from vision.house.parse import build_agents

__all__ = [
    "AgentModels",
    "GridHouse",
    "HouseError",
    "UnknownRoom",
    "agent_models",
    "make_house",
    "seed_personas",
]


def make_house(config: Config, bus: Bus) -> GridHouse:
    """Build the house. Reads nothing until the plan is first asked for."""
    return GridHouse(config, bus)


def seed_personas(config: Config) -> None:
    """Copy the default agent personas into the vault without overwriting the user's."""
    store.seed_personas(config.paths.house)


class AgentModels(NamedTuple):
    model: str
    heavy_model: str | None
    """None when the agent has no heavy model (the host falls back to `[brain]`)."""


def agent_models(config: Config, agent_id: str) -> AgentModels:
    """An agent's models, read from the house files without creating or changing them.

    If the user's file is missing or invalid, the default house answers.
    Raises `KeyError` for an unknown agent.
    """
    default = store.read_toml(store.DEFAULT_FILE)
    agents = build_agents(default, {}, config)
    if config.paths.house_file.is_file():
        try:
            agents = build_agents(default, store.read_toml(config.paths.house_file), config)
        except HouseError:
            pass
    if agent_id not in agents:
        raise KeyError(f"No agent with the id {agent_id!r}; known: {', '.join(agents)}.")
    agent = agents[agent_id]
    return AgentModels(agent.model, agent.heavy_model)
