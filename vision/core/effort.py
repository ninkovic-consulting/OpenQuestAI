"""Thinking effort: the levels there are, and which each Claude model accepts.

Effort (`output_config.effort`) sets how much a Claude model thinks and how
many tokens it spends: a higher level answers more carefully, more slowly and
at a higher cost. From Anthropic's API reference (the `claude-api` skill,
cached 2026-11-03): the Fable and Mythos 5 models, Opus 5.5, 5, 4.8 and 4.7,
Sonnet 5.5 and 5 and Haiku 5.5 take all five levels; Opus 4.6 and Sonnet 4.6
take every level but `xhigh`; Haiku 4.5 takes none (the parameter is an
error there). A model this table does not know is offered all five; the API
answers for it. Local models have no effort setting and ignore it.
"""

from __future__ import annotations

from typing import Literal, get_args

Effort = Literal["low", "medium", "high", "xhigh", "max"]
LEVELS: tuple[Effort, ...] = get_args(Effort)
NO_XHIGH: tuple[Effort, ...] = ("low", "medium", "high", "max")
_BY_PREFIX: tuple[tuple[str, tuple[Effort, ...]], ...] = (
    ("claude-haiku-4-5", ()),
    ("claude-opus-4-6", NO_XHIGH),
    ("claude-sonnet-4-6", NO_XHIGH),
)

TALK = "low"
HEAVY = "high"
"""The host's levels unless `[brain] talk_effort` and `heavy_effort` say otherwise."""
RESIDENT = "medium"
CAREFUL = "high"
"""A resident's levels unless its `effort` and `heavy_effort` in the house file say otherwise."""


def accepted(model: str) -> tuple[Effort, ...]:
    """The levels `model` accepts, lowest first; empty when it takes no effort at all."""
    for prefix, levels in _BY_PREFIX:
        if model.startswith(prefix):
            return levels
    return LEVELS


def problem(model: str, level: str) -> str | None:
    """Why `model` cannot run at `level`, in words for people; None when it can."""
    if level not in LEVELS:
        return f"An effort level is one of {', '.join(LEVELS)}."
    levels = accepted(model)
    if level in levels or not levels:
        # A model that takes no effort keeps whatever level is stored: none is sent (`usable`),
        # and refusing would make such a model impossible to choose.
        return None
    return f"{model} does not take effort {level}; it takes {', '.join(levels)}."


def usable(model: str, level: str) -> Effort | None:
    """The level to send: `level` when the model takes it, else the nearest lower one it
    takes, else None (send no effort). A room's own model may differ from the agent's."""
    levels = accepted(model)
    wanted = LEVELS.index(level) if level in LEVELS else LEVELS.index(RESIDENT)
    lower = [lv for lv in levels if LEVELS.index(lv) <= wanted]
    if lower:
        return lower[-1]
    return levels[0] if levels else None


def table(models: list[str]) -> dict[str, list[str]]:
    """The levels each named model accepts, for the window to offer only those."""
    return {m: list(accepted(m)) for m in dict.fromkeys(models)}
