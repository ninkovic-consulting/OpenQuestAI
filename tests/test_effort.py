"""Thinking effort as a setting: the levels each model takes, the host's from `[brain]`, each
resident's from the house file, refusals naming what a model takes, and what is sent."""

from __future__ import annotations

from typing import Any

import pytest
from settings_fakes import client, use
from test_brains_claude import StubStream, collect, make_brain, text_message
from test_residents import Client, World, seeded, text  # noqa: F401 - `seeded` is a fixture

from vision.app import Daemon
from vision.core import effort
from vision.core.config import Config
from vision.house import HouseError, build_agents


def test_levels_per_model() -> None:
    assert effort.accepted("claude-opus-5-5") == effort.LEVELS
    assert effort.accepted("claude-haiku-5-5") == effort.LEVELS
    assert effort.accepted("claude-sonnet-4-6") == ("low", "medium", "high", "max")
    assert effort.accepted("claude-haiku-4-5") == ()
    assert effort.problem("claude-opus-4-6", "xhigh") == (
        "claude-opus-4-6 does not take effort xhigh; it takes low, medium, high, max."
    )
    assert effort.problem("claude-haiku-4-5", "low") is None  # nothing is sent, so nothing to refuse
    assert effort.usable("claude-haiku-4-5", "low") is None
    assert effort.problem("claude-opus-5-5", "turbo") is not None
    assert effort.usable("claude-sonnet-4-6", "xhigh") == "high"
    assert effort.usable("claude-haiku-4-5", "medium") is None


async def test_the_host_sends_its_configured_efforts(config: Config) -> None:
    config.brain.talk_effort = "medium"
    config.brain.heavy_effort = "max"
    brain, client_, _, _ = await make_brain(
        config,
        [StubStream(["a"], text_message("a")), StubStream(["b"], text_message("b", model="claude-opus-5-5"))],
    )
    await collect(brain, "Hi")
    await collect(brain, "Think", heavy=True)
    assert [r["output_config"] for r in client_.requests] == [{"effort": "medium"}, {"effort": "max"}]


async def test_a_model_without_effort_gets_none(config: Config) -> None:
    config.brain.talk_model = "claude-haiku-4-5"
    brain, client_, _, _ = await make_brain(config, [StubStream(["a"], text_message("a", model="claude-haiku-4-5"))])
    brain._models = type(brain._models)("claude-haiku-4-5", "claude-opus-5-5")
    await collect(brain, "Hi")
    assert "output_config" not in client_.requests[0]


def test_house_effort_is_checked_against_the_model(config: Config) -> None:
    default = {"agents": {"host": {"persona": "h.md"}, "maker": {"name": "Tink", "persona": "m.md", "model": "claude-sonnet-4-6"}}}
    agents = build_agents(default, {"agents": {"maker": {"effort": "max", "heavy_effort": "low"}}}, config)
    assert (agents["maker"].effort, agents["maker"].heavy_effort) == ("max", "low")
    assert (agents["host"].effort, agents["host"].heavy_effort) == ("low", "high")
    with pytest.raises(HouseError, match="does not take effort xhigh; it takes low, medium, high, max"):
        build_agents(default, {"agents": {"maker": {"effort": "xhigh"}}}, config)
    with pytest.raises(HouseError, match="the host's effort follows"):
        build_agents(default, {"agents": {"host": {"effort": "high"}}}, config)


async def test_a_resident_works_at_its_effort(seeded: Config) -> None:
    claude = Client([text("ok"), text("ok")])
    w = World(seeded, claude)
    for a in w.plan["agents"]:
        if a["id"] == "checker":
            a["effort"], a["heavy_effort"] = "low", "max"
    await w.run("Tock", "Check.")
    await w.run("Tock", "Check carefully.", careful=True)
    assert [r["output_config"] for r in claude.requests] == [{"effort": "low"}, {"effort": "max"}]


async def test_settings_take_and_refuse_effort(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        ok = await http.patch(
            "/api/settings",
            json={"models": {"talk_effort": "medium"}, "agents": {"checker": {"effort": "xhigh", "heavy_effort": "max"}}},
        )
        bad_level = await http.patch("/api/settings", json={"models": {"heavy_effort": "turbo"}})
        bad_host = await http.patch("/api/settings", json={"agents": {"host": {"effort": "high"}}})
        old_model = await http.patch(
            "/api/settings", json={"agents": {"checker": {"model": "claude-sonnet-4-6"}}}
        )
        plan = (await http.get("/api/house")).json()
    body: dict[str, Any] = ok.json()
    assert ok.status_code == 200 and "models.talk_effort" in body["applied"]
    assert daemon.config.brain.talk_effort == "medium" and body["settings"]["models"]["talk_effort"] == "medium"
    checker = next(a for a in plan["agents"] if a["id"] == "checker")
    assert (checker["effort"], checker["heavy_effort"]) == ("xhigh", "max")
    assert bad_level.status_code == 400 and "is one of low, medium" in bad_level.json()["detail"]["errors"][0]["message"]
    assert bad_host.status_code == 400 and "follows models.talk_effort" in bad_host.json()["detail"]["errors"][0]["message"]
    assert old_model.status_code == 400
    assert "does not take effort xhigh" in old_model.json()["detail"]["errors"][0]["message"]
