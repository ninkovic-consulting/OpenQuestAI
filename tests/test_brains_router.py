"""Router fallback and recovery, with fake brains."""

from __future__ import annotations

from typing import Any

import pytest

from vision.brains import make_brain, make_engine
from vision.brains.router import LOCAL_LINE, Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BrainFallback, Notice
from vision.core.interfaces import Brain, BrainError, TextDelta, TurnDone
from vision.testing.fakes import FakeBrain, FakeBudget, FakeMemory, FakeToolHost


class FakeClaude(FakeBrain):
    def __init__(self, replies: list[Any], *, key: bool = True) -> None:
        super().__init__(replies, delay=0, name="claude", model="claude-haiku-5-5")
        self.has_key = key
        self.reloads = 0

    async def reload_key(self) -> bool:
        self.reloads += 1
        return self.has_key


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


RATE = BrainError("rate_limit", "Claude is rate limited right now.", True)
AUTH = BrainError("auth", "The Anthropic API key was rejected.", False)
CREDITS = BrainError("credits", "The Anthropic account has no credit left.", False)
BAD = BrainError("bad_request", "Claude rejected the request.", False)


def build(
    config: Config, claude_replies: list[Any], *, key: bool = True, budget: FakeBudget | None = None
) -> tuple[Router, FakeClaude, FakeBrain, Bus, Clock, Any]:
    config.brain.retry_claude_after_s = 60
    bus, clock = Bus(), Clock()
    sub = bus.subscribe({BrainFallback.TYPE, Notice.TYPE})
    claude = FakeClaude(claude_replies, key=key)
    local = FakeBrain(["Local answer."], delay=0, name="local", model="qwen")
    router = Router(config, bus, claude, local, budget or FakeBudget(), clock=clock)  # type: ignore[arg-type]
    return router, claude, local, bus, clock, sub


def events_of(sub: Any) -> list[Any]:
    out = []
    while not sub._queue.empty():
        out.append(sub._queue.get_nowait())
    return out


async def run(router: Router, text: str = "hi") -> tuple[str, list[Any]]:
    events = [e async for e in router.send(text)]
    return "".join(e.text for e in events if isinstance(e, TextDelta)), events


def test_factory_returns_a_router_without_io(config: Config) -> None:
    bus = Bus()
    brain = make_brain(config, bus, FakeToolHost(), FakeMemory(), FakeBudget(), make_engine(config, bus))
    assert isinstance(brain, Router) and isinstance(brain, Brain)
    assert brain.name == "claude"


async def test_offline_sends_nothing_to_claude(config: Config) -> None:
    router, claude, local, _, _, sub = build(config, ["From Claude."])
    await router.start()
    config.brain.offline = True
    assert router.name == "local"
    said, events = await run(router)
    assert said == "Local answer." and isinstance(events[-1], TurnDone)  # no spoken switch line
    assert claude.sent == [] and local.sent == [("hi", False)]
    assert not any(isinstance(e, BrainFallback) for e in events_of(sub))
    config.brain.offline = False
    assert router.name == "claude"
    said, _ = await run(router)
    assert said == "From Claude." and claude.sent == [("hi", False)]


async def test_claude_answers_when_healthy(config: Config) -> None:
    router, claude, local, _, _, sub = build(config, ["From Claude."])
    await router.start()
    text, events = await run(router)
    assert text == "From Claude." and router.name == "claude"
    assert isinstance(events[-1], TurnDone)
    assert local.sent == [] and events_of(sub) == []


async def test_one_retry_then_claude_answers(config: Config) -> None:
    router, claude, local, _, _, sub = build(config, [RATE, "Second try."])
    await router.start()
    text, _ = await run(router)
    assert text == "Second try." and len(claude.sent) == 2 and local.sent == []
    assert events_of(sub) == []


async def test_falls_back_after_retry_and_says_so(config: Config) -> None:
    router, claude, local, _, _, sub = build(config, [RATE, RATE])
    await router.start()
    text, _ = await run(router)
    assert len(claude.sent) == 2 and local.sent == [("hi", False)]
    assert text == LOCAL_LINE + "Local answer."
    assert router.name == "local"
    [fallback] = events_of(sub)
    assert isinstance(fallback, BrainFallback)
    assert (fallback.from_, fallback.to, fallback.reason) == ("claude", "local", RATE.message)

    text, _ = await run(router)  # still cooling down: local, no repeated announcement
    assert text == "Local answer." and len(claude.sent) == 2


async def test_auth_failure_falls_back_without_retry(config: Config) -> None:
    router, claude, local, _, _, _ = build(config, [AUTH])
    await router.start()
    await run(router)
    assert len(claude.sent) == 1 and len(local.sent) == 1


async def test_bad_request_is_not_hidden_by_fallback(config: Config) -> None:
    router, claude, local, _, _, _ = build(config, [BAD])
    await router.start()
    _, events = await run(router)
    assert events == [BAD] and local.sent == [] and router.name == "claude"


async def test_tries_claude_again_after_cooldown_and_announces_recovery(config: Config) -> None:
    router, claude, local, _, clock, sub = build(config, [RATE, RATE, RATE, RATE, "Back."])
    await router.start()
    await run(router)
    events_of(sub)
    clock.now += 61
    await run(router)  # probe fails twice: quietly stays local
    assert len(claude.sent) == 4 and router.name == "local" and events_of(sub) == []
    clock.now += 61
    text, _ = await run(router)
    assert text == "Back." and router.name == "claude"
    [recovered] = events_of(sub)
    assert (recovered.from_, recovered.to) == ("local", "claude")


async def test_no_key_runs_local_from_start_with_notice(config: Config) -> None:
    router, claude, local, _, clock, sub = build(config, ["unused"], key=False)
    await router.start()
    assert router.name == "local"
    [notice] = events_of(sub)
    assert isinstance(notice, Notice) and "Settings, under API key" in notice.text
    assert config.assistant.name in notice.text
    text, _ = await run(router)
    assert text == LOCAL_LINE + "Local answer." and claude.sent == []

    claude.has_key = True  # the user ran `vision auth`
    clock.now += 61
    text, _ = await run(router)
    assert text == "unused" and router.name == "claude"


async def test_exhausted_budget_runs_local_with_notice(config: Config) -> None:
    budget = FakeBudget(cap_usd=0.0)
    router, claude, _, _, _, sub = build(config, ["unused"], budget=budget)
    await router.start()
    assert router.name == "local"
    assert "monthly_cap_usd" in events_of(sub)[0].text
    await run(router)
    assert claude.sent == []


async def test_budget_reaching_cap_mid_session_switches(config: Config) -> None:
    budget = FakeBudget(cap_usd=1.0)
    router, claude, local, _, _, sub = build(config, ["A.", "B."], budget=budget)
    await router.start()
    await run(router)
    budget.spent_usd = 1.0
    text, _ = await run(router)
    assert text == LOCAL_LINE + "Local answer." and len(claude.sent) == 1
    [fallback] = events_of(sub)
    assert "budget" in fallback.reason


async def test_credits_exhausted_stays_local_for_the_month(config: Config) -> None:
    router, claude, _, _, clock, sub = build(config, [CREDITS, "unused"])
    await router.start()
    await run(router)
    kinds = [type(e) for e in events_of(sub)]
    assert Notice in kinds and BrainFallback in kinds
    clock.now += 10_000
    await run(router)
    assert len(claude.sent) == 1 and router.name == "local"


async def test_partial_reply_then_failure_is_reported_not_repeated(config: Config) -> None:
    class Flaky(FakeClaude):
        async def send(self, text: str, *, heavy: bool = False, images=()):
            self.sent.append((text, heavy))
            yield TextDelta("Half")
            yield RATE

    bus = Bus()
    local = FakeBrain(["Local."], delay=0, name="local")
    router = Router(config, bus, Flaky(["x"]), local, FakeBudget())  # type: ignore[arg-type]
    await router.start()
    _, events = await run(router)
    assert events == [TextDelta("Half"), RATE] and local.sent == []
    assert router.name == "local"


async def test_interrupt_and_close_reach_both_brains(config: Config) -> None:
    router, claude, local, _, _, _ = build(config, ["x"])
    await router.interrupt()
    await router.close()
    assert claude.interrupts == local.interrupts == 1
    assert claude.closed and local.closed


@pytest.mark.parametrize("heavy", [True, False])
async def test_heavy_flag_is_passed_through(config: Config, heavy: bool) -> None:
    router, claude, _, _, _, _ = build(config, ["x"])
    await router.start()
    _ = [e async for e in router.send("think it through", heavy=heavy)]
    assert claude.sent == [("think it through", heavy)]


async def test_name_is_local_before_the_turn_once_the_cap_is_reached(config: Config) -> None:
    router, *_ = build(config, ["unused"], budget=FakeBudget(cap_usd=0.0))
    await router.start()
    assert router.name == "local"
