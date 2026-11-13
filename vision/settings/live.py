"""Putting a freshly loaded config into the running daemon.

The daemon's parts hold the shared `Config` (the gate holds `config.gate`
itself), so values are copied into the live objects in place. What only a
restart applies (the Claude models, the server, the paths) is left as it
runs. Of `[brain]`, offline mode, the local model and the host's efforts
(`LIVE_BRAIN`) apply at once: the router reads `offline` on every turn, the
residents on every job, the local engine follows the model on its next
generation, and Claude reads the effort on every call. A change to offline
mode or the local model is announced with `brain.mode` and a notice.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel

from vision import brains
from vision.core.config import Config
from vision.core.events import BudgetUpdate
from vision.house import HouseError

if TYPE_CHECKING:
    from vision.app import Daemon

LIVE_SECTIONS = ("assistant", "budget", "voice", "gate", "automations", "jobs", "presence")
"""Copied into the running config."""
APPLIED_AT_ONCE = ("assistant", "voice", "gate", "automations", "jobs", "presence", "agents")
BUDGET_AT_ONCE = ("monthly_cap_usd", "prices")
LOCAL_BRAIN = ("offline", "local_backend", "local_model", "local_base_url")
LIVE_BRAIN = (*LOCAL_BRAIN, "talk_effort", "heavy_effort")
"""The `[brain]` keys that apply at once; a change to the local ones is announced."""


@runtime_checkable
class EditableHouse(Protocol):
    """What `vision.house.GridHouse` offers beyond the `House` protocol."""

    async def refresh(self) -> None: ...
    async def reload(self) -> None: ...
    async def update_agents(self, changes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]: ...


def needs_restart(old: Config, new: Config) -> bool:
    """True when `new` differs from `old` in something only a restart applies."""
    return _restart_part(old) != _restart_part(new)


def _restart_part(config: Config) -> dict[str, Any]:
    dump = config.model_dump(mode="json")
    for section in APPLIED_AT_ONCE:
        dump.pop(section, None)
    for key in BUDGET_AT_ONCE:
        dump["budget"].pop(key, None)
    for key in LIVE_BRAIN:
        dump["brain"].pop(key, None)
    return dump


async def apply(daemon: Daemon, fresh: Config) -> None:
    """Copy `fresh` into the live config and tell the parts that follow it."""
    live = daemon.config
    old = live.model_copy(deep=True)
    for section in LIVE_SECTIONS:
        _copy_into(getattr(live, section), getattr(fresh, section))
    live.agents.clear()
    live.agents.update(fresh.agents)
    for key in LIVE_BRAIN:
        setattr(live.brain, key, getattr(fresh.brain, key))

    renamed = old.assistant.name != live.assistant.name
    if renamed or old.agents != live.agents:
        await refresh_house(daemon)
    if old.budget.monthly_cap_usd != live.budget.monthly_cap_usd:
        budget = daemon.components.budget
        budget.set_cap(live.budget.monthly_cap_usd)
        daemon.bus.publish(BudgetUpdate(**dataclasses.asdict(budget.status())))
    if any(getattr(old.brain, k) != getattr(live.brain, k) for k in LOCAL_BRAIN):
        announce_mode(daemon, was_offline=old.brain.offline)
    if old.jobs != live.jobs:
        daemon.board.pump()  # a higher limit may let waiting jobs start
    if old.presence != live.presence:
        daemon.presence.check()  # announces the new away time, and away or back at once
    # A failed start is retried too: a new microphone is often the fix for the last failure.
    failed = live.voice.enabled and daemon.voice_error is not None
    if (daemon.voice_running or failed) and (renamed or old.voice != live.voice):
        await daemon.set_voice(True)


def announce_mode(daemon: Daemon, *, was_offline: bool) -> None:
    """Publish `brain.mode`, and a notice when offline mode was switched."""
    brain = daemon.config.brain
    daemon.bus.publish(brains.mode(daemon.config, daemon.components.brain.name, daemon.local))
    name = daemon.config.assistant.name
    if brain.offline and not was_offline:
        daemon.notice(
            "info",
            f"Offline mode is on: {name} and the residents now work on the local model "
            f"{brain.local_model}, and nothing is sent to Anthropic.",
        )
    elif was_offline and not brain.offline:
        daemon.notice(
            "info",
            "Offline mode is off: new turns and new jobs go to Claude again. A job already "
            "running finishes on the local model.",
        )
    elif brain.offline:
        daemon.notice("info", f"Offline, {name} now answers on the local model {brain.local_model}.")


async def refresh_house(daemon: Daemon) -> None:
    house = daemon.components.house
    if not isinstance(house, EditableHouse):
        return
    try:
        await house.refresh()
    except HouseError as exc:
        daemon.notice("warn", f"The house could not follow the new settings: {exc}")


def _copy_into(dst: BaseModel, src: BaseModel) -> None:
    for name in type(src).model_fields:
        value = getattr(src, name)
        current = getattr(dst, name)
        if isinstance(current, dict) and isinstance(value, dict):
            current.clear()
            current.update(value)
        else:
            setattr(dst, name, value)
    extra = dst.model_extra
    if extra is not None:
        extra.clear()
        extra.update(src.model_extra or {})
