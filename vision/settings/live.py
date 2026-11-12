"""Putting a freshly loaded config into the running daemon.

The daemon's parts hold the shared `Config` (the gate holds `config.gate`
itself), so values are copied into the live objects in place. What only a
restart applies (`[brain]`, the server, the paths) is left as it runs: the
brains read `[brain]` as they go, and must keep the models they started with.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel

from vision.core.config import Config
from vision.core.events import BudgetUpdate
from vision.house import HouseError

if TYPE_CHECKING:
    from vision.app import Daemon

LIVE_SECTIONS = ("assistant", "budget", "voice", "gate", "automations")
"""Copied into the running config."""
APPLIED_AT_ONCE = ("assistant", "voice", "gate", "automations", "agents")
BUDGET_AT_ONCE = ("monthly_cap_usd", "prices")


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
    return dump


async def apply(daemon: Daemon, fresh: Config) -> None:
    """Copy `fresh` into the live config and tell the parts that follow it."""
    live = daemon.config
    old = live.model_copy(deep=True)
    for section in LIVE_SECTIONS:
        _copy_into(getattr(live, section), getattr(fresh, section))
    live.agents.clear()
    live.agents.update(fresh.agents)

    renamed = old.assistant.name != live.assistant.name
    if renamed or old.agents != live.agents:
        await refresh_house(daemon)
    if old.budget.monthly_cap_usd != live.budget.monthly_cap_usd:
        budget = daemon.components.budget
        budget.set_cap(live.budget.monthly_cap_usd)
        daemon.bus.publish(BudgetUpdate(**dataclasses.asdict(budget.status())))
    if daemon.voice_running and (renamed or old.voice != live.voice):
        await daemon.set_voice(True)


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
