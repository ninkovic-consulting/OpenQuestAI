"""Monthly API spend, priced from `config.budget.prices` and persisted under `$VISION_HOME`.

The running total lives in `<home>/budget.json` (mode 0600). It is read on first
use (never in the constructor) and rewritten after every priced call. A new
calendar month starts again from zero. A model missing from the price table is
charged at the highest known rate, with one notice per model, never as free.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from vision.core.bus import Bus
from vision.core.config import Config, Price, ceiling_price
from vision.core.events import BudgetUpdate, Notice
from vision.core.interfaces import BudgetStatus

log = logging.getLogger(__name__)

FILE_NAME = "budget.json"


def usd(amount: float) -> str:
    """Dollars for people: cents normally, more digits for amounts under ten cents."""
    return f"${amount:.2f}" if amount >= 0.1 else f"${amount:.2g}"


class MonthlyBudget:
    """Adds up what each model call cost and enforces the monthly cap."""

    def __init__(self, config: Config, bus: Bus, *, now: Callable[[], datetime] = datetime.now) -> None:
        self._prices = config.budget.prices
        self._budget_config = config.budget
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
        self._unpriced: set[str] = set()

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
        price = self._prices.get(model) or self._unknown(model)
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

    def record_searches(self, count: int) -> float:
        """Web searches are priced per thousand, not per token; the price is read live."""
        if count <= 0:
            return 0.0
        self._sync_month()
        cost = count * self._budget_config.web_search_per_1k_usd / 1000
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

    def set_cap(self, cap_usd: float) -> None:
        """Change the monthly cap now. Warns or caps at once if the spend already passed it."""
        self._sync_month()
        self._cap = cap_usd
        self._warned = self._warned and self._spent >= cap_usd * self._warn_fraction
        self._capped = self._capped and self._spent >= cap_usd
        self._check_thresholds()
        self._save()

    def reload(self) -> None:
        """Read `budget.json` again on next use (after it was reset or restored)."""
        self._loaded = False
        self._month, self._spent, self._warned, self._capped = "", 0.0, False, False

    # ------------------------------------------------------------ internals

    def _unknown(self, model: str) -> Price:
        if model not in self._unpriced:
            self._unpriced.add(model)
            self._bus.publish(
                Notice(
                    level="warn",
                    text=(
                        f"{model} has no price in [budget.prices], so it is counted at the "
                        "highest known rate. Add its price to config.toml for an exact total."
                    ),
                )
            )
        return ceiling_price(self._prices)

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
                        f"This month's API spend reached the {usd(self._cap)} cap, so talk moves "
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
                        f"API spend this month is {usd(self._spent)}, "
                        f"{self._warn_fraction:.0%} of the {usd(self._cap)} cap."
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
            # Flags only hold while the cap they were raised for still applies.
            self._warned = bool(data.get("warned", False)) and (
                self._spent >= self._cap * self._warn_fraction
            )
            self._capped = bool(data.get("capped", False)) and self._spent >= self._cap
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
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(data))
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except OSError as exc:
            log.warning("could not save the budget: %s", exc)
