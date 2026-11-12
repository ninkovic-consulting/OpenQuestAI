"""Monthly API spend, priced from `config.budget.prices` and persisted under `$VISION_HOME`.

The running total lives in `<home>/budget.json`. It is read on first use (never
in the constructor) and rewritten after every priced call. A new calendar month
starts again from zero.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BudgetUpdate, Notice
from vision.core.interfaces import BudgetStatus

log = logging.getLogger(__name__)

FILE_NAME = "budget.json"


class MonthlyBudget:
    """Adds up what each model call cost and enforces the monthly cap."""

    def __init__(self, config: Config, bus: Bus, *, now: Callable[[], datetime] = datetime.now) -> None:
        self._prices = config.budget.prices
        self._cap = config.budget.monthly_cap_usd
        self._warn_fraction = config.budget.warn_fraction
        self._path: Path = config.paths.home / FILE_NAME
        self._bus = bus
        self._now = now
        self._loaded = False
        self._month = ""
        self._spent = 0.0
        self._warned = False
        self._capped = False

    # ------------------------------------------------------------ protocol

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        self._sync_month()
        price = self._prices.get(model)
        if price is None:
            return 0.0
        cost = (
            input_tokens * price.input_per_mtok
            + output_tokens * price.output_per_mtok
            + cache_read_tokens * price.cache_read_per_mtok
            + cache_write_tokens * price.cache_write_per_mtok
        ) / 1_000_000
        if cost <= 0:
            return 0.0
        self._spent += cost
        self._check_thresholds()
        self._save()
        self._publish()
        return cost

    def status(self) -> BudgetStatus:
        self._sync_month()
        return BudgetStatus(self._month, round(self._spent, 6), self._cap)

    def exhausted(self) -> bool:
        self._sync_month()
        return self._spent >= self._cap

    # ------------------------------------------------------------ internals

    def _current_month(self) -> str:
        return self._now().strftime("%Y-%m")

    def _sync_month(self) -> None:
        if not self._loaded:
            self._load()
        month = self._current_month()
        if month != self._month:
            self._month, self._spent, self._warned, self._capped = month, 0.0, False, False
            self._save()
            self._publish()

    def _check_thresholds(self) -> None:
        if not self._capped and self._spent >= self._cap:
            self._capped = self._warned = True
            self._bus.publish(
                Notice(
                    level="warn",
                    text=(
                        f"This month's API spend reached the ${self._cap:.2f} cap, so talk moves "
                        "to the local model until the month turns. Raise "
                        "[budget] monthly_cap_usd in config.toml to continue on Claude."
                    ),
                )
            )
        elif not self._warned and self._spent >= self._cap * self._warn_fraction:
            self._warned = True
            self._bus.publish(
                Notice(
                    level="info",
                    text=(
                        f"API spend this month is ${self._spent:.2f}, "
                        f"{self._warn_fraction:.0%} of the ${self._cap:.2f} cap."
                    ),
                )
            )

    def _publish(self) -> None:
        self._bus.publish(
            BudgetUpdate(month=self._month, spent_usd=round(self._spent, 6), cap_usd=self._cap)
        )

    def _load(self) -> None:
        self._loaded = True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._month = str(data["month"])
            self._spent = float(data["spent_usd"])
            self._warned = bool(data.get("warned", False))
            self._capped = bool(data.get("capped", False))
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("budget file unreadable, starting from zero: %s", exc)

    def _save(self) -> None:
        data = {
            "month": self._month,
            "spent_usd": self._spent,
            "warned": self._warned,
            "capped": self._capped,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            log.warning("could not save the budget: %s", exc)
