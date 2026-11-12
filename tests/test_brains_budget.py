from __future__ import annotations

import json
from datetime import datetime

import pytest

from vision.brains import make_budget
from vision.brains.budget import FILE_NAME, MonthlyBudget
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BudgetUpdate, Notice
from vision.core.interfaces import Budget


class Clock:
    def __init__(self, when: datetime) -> None:
        self.when = when

    def __call__(self) -> datetime:
        return self.when


def drain(sub) -> list:
    out = []
    while not sub._queue.empty():
        out.append(sub._queue.get_nowait())
    return out


def test_factory_does_no_io(config: Config) -> None:
    budget = make_budget(config, Bus())
    assert isinstance(budget, Budget)
    assert not (config.paths.home / FILE_NAME).exists()


def test_cost_maths_includes_cache_tokens(config: Config) -> None:
    budget = MonthlyBudget(config, Bus())
    cost = budget.record(
        "claude-haiku-5-5", 4000, 150, cache_read_tokens=10_000, cache_write_tokens=2000
    )
    expected = (4000 * 0.10 + 150 * 0.50 + 10_000 * 0.01 + 2000 * 0.125) / 1e6
    assert cost == pytest.approx(expected)
    opus = budget.record("claude-opus-5-5", 1000, 100, cache_read_tokens=1000, cache_write_tokens=1000)
    assert opus == pytest.approx((1000 * 4 + 100 * 20 + 1000 * 0.2 + 1000 * 5) / 1e6)
    assert budget.status().spent_usd == pytest.approx(expected + opus)


def test_local_model_is_free_and_silent(config: Config) -> None:
    bus = Bus()
    sub = bus.subscribe()
    budget = MonthlyBudget(config, bus, now=Clock(datetime(2026, 11, 12)))
    budget.status()
    drain(sub)
    assert budget.record("qwen3.8:27b-mlx", 1000, 1000) == 0
    assert drain(sub) == []


def test_persists_and_reloads(config: Config) -> None:
    clock = Clock(datetime(2026, 11, 12))
    first = MonthlyBudget(config, Bus(), now=clock)
    first.record("claude-haiku-5-5", 1_000_000, 0)
    data = json.loads((config.paths.home / FILE_NAME).read_text())
    assert data["month"] == "2026-11"
    assert data["spent_usd"] == pytest.approx(0.10)
    second = MonthlyBudget(config, Bus(), now=clock)
    assert second.status().spent_usd == pytest.approx(0.10)


def test_rolls_over_on_new_month(config: Config) -> None:
    clock = Clock(datetime(2026, 11, 30, 23, 59))
    bus = Bus()
    budget = MonthlyBudget(config, bus, now=clock)
    budget.record("claude-haiku-5-5", 1_000_000, 0)
    sub = bus.subscribe()
    clock.when = datetime(2026, 12, 1, 0, 1)
    status = budget.status()
    assert (status.month, status.spent_usd) == ("2026-12", 0.0)
    assert [e for e in drain(sub) if isinstance(e, BudgetUpdate)][0].month == "2026-12"
    reloaded = MonthlyBudget(config, Bus(), now=clock)
    assert reloaded.status().spent_usd == 0.0


def test_publishes_budget_and_warns_once_then_caps(config: Config) -> None:
    config.budget.monthly_cap_usd = 1.0
    bus = Bus()
    sub = bus.subscribe()
    budget = MonthlyBudget(config, bus, now=Clock(datetime(2026, 11, 12)))
    budget.record("claude-opus-5-5", 0, 40_000)  # $0.80
    events = drain(sub)
    updates = [e for e in events if isinstance(e, BudgetUpdate)]
    assert updates[-1].spent_usd == pytest.approx(0.80) and updates[-1].cap_usd == 1.0
    notices = [e for e in events if isinstance(e, Notice)]
    assert len(notices) == 1 and "80%" in notices[0].text
    assert not budget.exhausted()

    budget.record("claude-opus-5-5", 0, 5000)  # $0.90, no second warning
    assert not [e for e in drain(sub) if isinstance(e, Notice)]

    budget.record("claude-opus-5-5", 0, 5000)  # $1.00
    caps = [e for e in drain(sub) if isinstance(e, Notice)]
    assert len(caps) == 1 and "monthly_cap_usd" in caps[0].text
    assert budget.exhausted()


def test_corrupt_file_starts_from_zero(config: Config) -> None:
    config.paths.home.mkdir(parents=True, exist_ok=True)
    (config.paths.home / FILE_NAME).write_text("{not json")
    assert MonthlyBudget(config, Bus()).status().spent_usd == 0.0
