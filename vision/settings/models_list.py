"""The Claude models to choose from: the Models API, cached for an hour, else a built-in list."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Literal

from vision.core import effort
from vision.core.config import BudgetConfig, Config
from vision.settings.outside import KeyRefused, ModelRow, Outside, Unreachable

CACHE_S = 3600.0
Source = Literal["api", "cache", "built_in"]
Verdict = Literal["accepted", "refused", "unreachable", "none"]

RETIRES: dict[str, str] = {"claude-sonnet-4-5": "2026-11-30"}
"""Scheduled retirements the built-in list knows of."""


def display_name(model_id: str) -> str:
    """`claude-opus-4-8` -> `Claude Opus 4.8`."""
    words = model_id.split("-")
    names = [w.capitalize() for w in words if not w.isdigit()]
    version = ".".join(w for w in words if w.isdigit())
    return " ".join([*names, version]).strip()


def built_in() -> list[ModelRow]:
    priced = list(BudgetConfig().prices)
    ids = [*priced, *(m for m in RETIRES if m not in priced)]
    return [ModelRow(i, display_name(i), None, None, RETIRES.get(i)) for i in ids]


class ModelCatalog:
    def __init__(self, outside: Callable[[], Outside], now: Callable[[], float] = time.time) -> None:
        self._outside = outside
        self._now = now
        self._rows: list[ModelRow] | None = None
        self._fetched_at: float | None = None

    async def listing(self, config: Config) -> dict[str, Any]:
        """The `GET /api/models` answer."""
        fresh = self._fetched_at is not None and self._now() - self._fetched_at < CACHE_S
        source: Source = "cache"
        if not fresh:
            outside = self._outside()
            key = await asyncio.to_thread(outside.api_key)
            if key is not None and await self.fetch(key) == "accepted":
                source = "api"
        if self._rows is None:
            return _answer("built_in", None, built_in(), config)
        return _answer(source, self._fetched_at, self._rows, config)

    async def fetch(self, key: str) -> Verdict:
        """List models with `key`, refreshing the cache when the API accepts it."""
        try:
            rows = await asyncio.to_thread(self._outside().list_models, key)
        except KeyRefused:
            return "refused"
        except Unreachable:
            return "unreachable"
        self._rows, self._fetched_at = rows, self._now()
        return "accepted"


def _answer(
    source: Source, fetched_at: float | None, rows: list[ModelRow], config: Config
) -> dict[str, Any]:
    prices = config.budget.prices
    return {
        "source": source,
        "fetched_at": fetched_at,
        "models": [
            {
                "id": r.id,
                "display_name": r.display_name,
                "max_input_tokens": r.max_input_tokens,
                "max_tokens": r.max_tokens,
                "retires_at": r.retires_at,
                "efforts": list(effort.accepted(r.id)),
                "price": (
                    {
                        "input_per_mtok": prices[r.id].input_per_mtok,
                        "output_per_mtok": prices[r.id].output_per_mtok,
                    }
                    if r.id in prices
                    else None
                ),
            }
            for r in rows
        ],
    }
