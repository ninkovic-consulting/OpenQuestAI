"""Which Claude models the host agent talks with.

The house owns the agents (`vision.house.agent_models(config, "host")`). Until
that function exists, the `[brain]` section of the config decides.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from vision.core.config import Config

log = logging.getLogger(__name__)

HOST_AGENT = "host"


@dataclass(frozen=True, slots=True)
class HostModels:
    talk: str
    heavy: str


def _field(source: Any, name: str) -> str | None:
    value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
    return value if isinstance(value, str) and value else None


def host_models(config: Config) -> HostModels:
    """The talk and heavy models: from the house when available, else from `[brain]`."""
    talk, heavy = config.brain.talk_model, config.brain.heavy_model
    try:
        from vision.house import agent_models  # type: ignore[attr-defined]

        found = agent_models(config, HOST_AGENT)
    except (ImportError, NotImplementedError):
        return HostModels(talk, heavy)
    except Exception:
        log.exception("vision.house.agent_models failed; using [brain] models")
        return HostModels(talk, heavy)
    return HostModels(_field(found, "model") or talk, _field(found, "heavy_model") or heavy)
