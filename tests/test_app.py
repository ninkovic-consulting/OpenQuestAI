import importlib.util

import pytest

from vision.app import build_components
from vision.brains.budget import MonthlyBudget
from vision.brains.router import Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import (
    Brain,
    Budget,
    House,
    Memory,
    Speaker,
    ToolHost,
    Voice,
)
from vision.gate.gate import ToolGate
from vision.house import GridHouse
from vision.memory.service import VaultMemory
from vision.testing.fakes import (
    FakeBrain,
    FakeBudget,
    FakeHouse,
    FakeMemory,
    FakeToolHost,
    FakeVoice,
)
from vision.voice import make_voice as real_make_voice


def test_every_part_comes_from_its_package(config: Config) -> None:
    components, notices = build_components(config, Bus())
    assert isinstance(components.brain, Router)
    assert isinstance(components.memory, VaultMemory)
    assert isinstance(components.budget, MonthlyBudget)
    assert isinstance(components.tools, ToolGate)
    assert isinstance(components.house, GridHouse)
    assert isinstance(components.voice, FakeVoice)  # the test guard in conftest
    assert notices == []


def test_real_voice_factory_builds_a_voice_without_io(config: Config) -> None:
    vox = real_make_voice(config, Bus())
    assert isinstance(vox, Voice)
    if importlib.util.find_spec("mlx_audio") is not None:
        from vision.voice.service import LocalVoice

        assert isinstance(vox, LocalVoice)


def test_voice_factory_can_be_replaced(config: Config) -> None:
    mine = FakeVoice()
    components, _ = build_components(config, Bus(), voice_factory=lambda config, bus: mine)
    assert components.voice is mine


def test_fake_brain_flag(config: Config) -> None:
    components, notices = build_components(config, Bus(), fake_brain=True)
    assert isinstance(components.brain, FakeBrain)
    assert any("--fake-brain" in n.text for n in notices)


def test_parts_satisfy_protocols(config: Config) -> None:
    components, _ = build_components(config, Bus())
    assert isinstance(components.brain, Brain)
    assert isinstance(components.memory, Memory)
    assert isinstance(components.budget, Budget)
    assert isinstance(components.tools, ToolHost)
    assert isinstance(components.voice, Voice)
    assert isinstance(components.voice.speaker, Speaker)
    assert isinstance(components.house, House)


def test_fakes_satisfy_protocols() -> None:
    assert isinstance(FakeBrain(), Brain)
    assert isinstance(FakeMemory(), Memory)
    assert isinstance(FakeBudget(), Budget)
    assert isinstance(FakeToolHost(), ToolHost)
    assert isinstance(FakeVoice(), Voice)
    assert isinstance(FakeHouse(), House)


def test_fake_budget_prices(config: Config) -> None:
    budget = FakeBudget.from_config(config)
    cost = budget.record("claude-haiku-5-5", 4000, 150)
    assert abs(cost - (4000 * 0.10 + 150 * 0.50) / 1e6) < 1e-12
    ceiling = (1000 * 5 + 1000 * 25) / 1e6
    assert budget.record("unpriced-model", 1000, 1000) == pytest.approx(ceiling)
    assert not budget.exhausted()
    budget.cap_usd = 0.0001
    assert budget.exhausted()


def test_fake_house_plan_has_the_spec_shape(config: Config) -> None:
    real = GridHouse(config, Bus()).plan()
    fake = FakeHouse().plan()
    assert set(fake) == set(real)
    assert set(fake["rooms"][0]) == set(real["rooms"][0])
    assert set(fake["agents"][0]) == set(real["agents"][0])
    hall = next(r for r in real["rooms"] if r["id"] == "hall")
    assert {k: hall[k] for k in ("at", "size", "kind", "shape", "agent")} == {
        k: fake["rooms"][0][k] for k in ("at", "size", "kind", "shape", "agent")
    }
