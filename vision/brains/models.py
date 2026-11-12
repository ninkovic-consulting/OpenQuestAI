"""Which Claude models the host agent talks with.

The house owns the agents (`vision.house.agent_models(config, "host")`); the
`[brain]` section of the config fills in what the house leaves out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vision.core.config import Config
from vision.house import agent_models

log = logging.getLogger(__name__)

HOST_AGENT = "host"


@dataclass(frozen=True, slots=True)
class HostModels:
    talk: str
    heavy: str


def host_models(config: Config) -> HostModels:
    """The talk and heavy models: from the house, else from `[brain]`."""
    talk, heavy = config.brain.talk_model, config.brain.heavy_model
    try:
        found = agent_models(config, HOST_AGENT)
    except Exception:
        log.exception("vision.house.agent_models failed; using [brain] models")
        return HostModels(talk, heavy)
    return HostModels(found.model or talk, found.heavy_model or heavy)
