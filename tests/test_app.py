from vision.app import build_components
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Brain, Budget, House, Memory, Speaker, ToolHost, Voice
from vision.testing.fakes import FakeBrain, FakeBudget, FakeHouse, FakeMemory, FakeToolHost, FakeVoice


def test_unbuilt_parts_fall_back_to_fakes_with_notices(config: Config) -> None:
    components, notices = build_components(config, Bus())
    assert isinstance(components.brain, FakeBrain)
    assert isinstance(components.memory, FakeMemory)
    assert isinstance(components.budget, FakeBudget)
    assert isinstance(components.tools, FakeToolHost)
    assert isinstance(components.voice, FakeVoice)
    assert isinstance(components.house, FakeHouse)
    assert len(notices) == 6
    assert all("not built yet" in n.text for n in notices)


def test_fake_brain_flag(config: Config) -> None:
    components, notices = build_components(config, Bus(), fake_brain=True)
    assert isinstance(components.brain, FakeBrain)
    assert any("--fake-brain" in n.text for n in notices)


def test_fakes_satisfy_protocols(config: Config) -> None:
    components, _ = build_components(config, Bus())
    assert isinstance(components.brain, Brain)
    assert isinstance(components.memory, Memory)
    assert isinstance(components.budget, Budget)
    assert isinstance(components.tools, ToolHost)
    assert isinstance(components.voice, Voice)
    assert isinstance(components.voice.speaker, Speaker)
    assert isinstance(components.house, House)


def test_fake_budget_prices(config: Config) -> None:
    budget = FakeBudget.from_config(config)
    cost = budget.record("claude-haiku-5-5", 4000, 150)
    assert abs(cost - (4000 * 0.10 + 150 * 0.50) / 1e6) < 1e-12
    assert budget.record("qwen3.8:27b-mlx", 1000, 1000) == 0
    assert not budget.exhausted()
    budget.cap_usd = 0.0001
    assert budget.exhausted()
