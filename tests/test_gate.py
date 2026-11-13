from __future__ import annotations

import asyncio
from typing import Any

import pytest

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import GateDecision, GateRequest, GateResolved, TurnSource
from vision.core.interfaces import ToolHost, ToolSpec
from vision.gate import make_tool_host
from vision.core.turns import TurnOrigin, set_origin
from vision.gate.gate import Actor, ToolGate, parse_yes_no
from vision.gate.policy import tier_for
from vision.gate.tools import Tool, ToolFailure
from vision.testing.fakes import FakeMemory


def make_tool(name: str, calls: list[dict[str, Any]], *, fail: bool = False) -> Tool:
    async def run(args: dict[str, Any]) -> str:
        calls.append(args)
        if fail:
            raise ToolFailure("it broke")
        return f"ran {name}"

    spec = ToolSpec(name, f"{name} tool", {"type": "object", "properties": {}})
    return Tool(spec, run, f"Use {name}", "command")


@pytest.fixture
def setup(config: Config) -> tuple[ToolGate, Bus, FakeMemory, list[dict[str, Any]]]:
    config.gate.tiers = {"free_tool": "free", "ask_tool": "ask", "banned": "never", "shell": "free"}
    config.gate.timeout_s = 5
    bus, memory, calls = Bus(), FakeMemory(), []
    tools = [make_tool(n, calls) for n in ("free_tool", "ask_tool", "banned", "shell")]
    return ToolGate(config, bus, memory, tools), bus, memory, calls


# ------------------------------------------------------------ policy


def test_policy_tiers(config: Config) -> None:
    gate = config.gate
    assert tier_for(gate, "remember") == "free"
    assert tier_for(gate, "shell") == "ask"
    assert tier_for(gate, "something_new") == gate.default_tier == "ask"
    gate.tiers["open_url"] = "never"
    assert tier_for(gate, "open_url") == "never"


def test_free_shell_holds_only_for_the_owner_at_the_mac(config: Config) -> None:
    config.gate.tiers["shell"] = "free"
    assert tier_for(config.gate, "shell", "text") == tier_for(config.gate, "shell", "voice") == "free"
    for source in ("automation", "job", "phone", None):
        assert tier_for(config.gate, "shell", source) == "ask"
    config.gate.tiers["shell"] = "never"
    assert tier_for(config.gate, "shell", "text") == "never"


def test_free_run_program_holds_only_in_a_job_the_owner_started_at_the_mac(config: Config) -> None:
    config.gate.tiers["run_program"] = "free"
    for via in ("text", "voice", "window"):
        assert tier_for(config.gate, "run_program", None, via) == "free"
    for via in ("phone", "automation", "job", "", "owner", "host", None):
        assert tier_for(config.gate, "run_program", None, via) == "ask"
    # outside a job (no `job_via`) it asks, even in the owner's own turn at the Mac
    assert tier_for(config.gate, "run_program", "text") == "ask"
    config.gate.tiers["run_program"] = "ask"
    assert tier_for(config.gate, "run_program", None, "text") == "ask"
    config.gate.tiers["run_program"] = "never"
    assert tier_for(config.gate, "run_program", None, "window") == "never"


def test_run_program_asks_by_default(config: Config) -> None:
    assert tier_for(config.gate, "run_program", None, "text") == "ask"


def test_start_project_and_shell_are_not_freed_by_a_job_from_the_mac(config: Config) -> None:
    config.gate.tiers["start_project"] = "free"
    config.gate.tiers["shell"] = "free"
    for via in ("text", "voice", "window"):
        assert tier_for(config.gate, "start_project", "text", via) == "ask"
        assert tier_for(config.gate, "shell", None, via) == "ask"


@pytest.mark.parametrize(
    ("text", "choice"),
    [
        ("Yes", "allow"),
        ("yeah go ahead", "allow"),
        ("Vision, do it.", "allow"),
        ("no", "deny"),
        ("Don't run that", "deny"),
        ("what is the weather", None),
        ("yes, no, maybe", None),
        ("", None),
        ("ok what is the weather like today", None),
        ("sure, but first tell me the time", None),
        ("yeah I was just telling her about the trip", None),
    ],
)
def test_parse_yes_no(text: str, choice: str | None) -> None:
    assert parse_yes_no(text) == choice


# ------------------------------------------------------------ gate


def test_factory_builds_the_five_tools_in_order(config: Config) -> None:
    host = make_tool_host(config, Bus(), FakeMemory())
    assert isinstance(host, ToolHost)
    assert [s.name for s in host.specs()] == ["remember", "recall", "open_app", "open_url", "shell"]


async def test_free_tool_runs_and_is_audited(setup) -> None:
    gate, bus, memory, calls = setup
    sub = bus.subscribe()
    result = await gate.call("free_tool", {"x": 1})
    assert result.ok and result.content == "ran free_tool"
    assert calls == [{"x": 1}]
    assert sub._queue.empty()
    [entry] = memory.audits
    assert (entry.tool, entry.tier, entry.decision, entry.result) == ("free_tool", "free", "allow", "ran free_tool")


async def answer_with(bus: Bus, decision: str) -> GateRequest:
    sub = bus.subscribe({GateRequest.TYPE})
    request = await asyncio.wait_for(sub.get(), 2)
    assert isinstance(request, GateRequest)
    bus.publish(GateDecision(id=request.id, decision=decision))
    return request


async def test_ask_allowed_runs(setup) -> None:
    gate, bus, memory, calls = setup
    resolved = bus.subscribe({GateResolved.TYPE})
    answer = asyncio.create_task(answer_with(bus, "allow"))
    await asyncio.sleep(0)
    result = await gate.call("ask_tool", {"command": "ls"})
    request = await answer
    assert request.tool == "ask_tool" and request.detail == "ls" and request.summary == "Use ask_tool"
    assert result.ok and calls == [{"command": "ls"}]
    event = resolved._queue.get_nowait()
    assert (event.id, event.decision) == (request.id, "allow")
    [entry] = memory.audits
    assert (entry.decision, entry.request_id, entry.tier) == ("allow", request.id, "ask")
    assert not gate.waiting


async def test_ask_denied_does_not_run(setup) -> None:
    gate, bus, memory, calls = setup
    answer = asyncio.create_task(answer_with(bus, "deny"))
    await asyncio.sleep(0)
    result = await gate.call("ask_tool", {"command": "rm -rf /tmp/x"})
    await answer
    assert not result.ok and "declined" in result.content
    assert calls == []
    assert memory.audits[0].decision == "deny"


async def test_ask_times_out_and_denies(setup) -> None:
    gate, bus, memory, calls = setup
    gate._gate.timeout_s = 0.05
    resolved = bus.subscribe({GateResolved.TYPE})
    result = await gate.call("ask_tool", {"command": "ls"})
    assert not result.ok and calls == []
    assert resolved._queue.get_nowait().decision == "timeout"
    assert memory.audits[0].decision == "timeout"


async def test_decision_for_another_request_is_ignored(setup) -> None:
    gate, bus, _, calls = setup
    gate._gate.timeout_s = 0.1
    task = asyncio.create_task(gate.call("ask_tool", {"command": "ls"}))
    await asyncio.sleep(0.01)
    bus.publish(GateDecision(id="someone-else", decision="allow"))
    result = await task
    assert not result.ok and calls == []


async def test_free_shell_outside_a_turn_asks_and_answer_resolves_by_text(setup) -> None:
    gate, bus, memory, calls = setup
    assert not gate.answer("yes")  # nothing waiting
    task = asyncio.create_task(gate.call("shell", {"command": "date"}))
    await asyncio.sleep(0.01)
    assert gate.waiting
    assert not gate.answer("what time is it")
    assert gate.answer("yes please")
    result = await task
    assert result.ok and calls == [{"command": "date"}]
    assert memory.audits[0].tier == "ask"


async def test_free_shell_runs_at_once_in_the_owners_turn_and_is_audited(setup) -> None:
    gate, _, memory, calls = setup
    set_origin(TurnOrigin("voice"))
    result = await gate.call("shell", {"command": "date"})
    assert result.ok and calls == [{"command": "date"}]
    audit = memory.audits[0]
    assert (audit.tool, audit.tier, audit.decision, audit.request_id) == ("shell", "free", "allow", "")


@pytest.mark.parametrize("source", ["automation", "job", "phone"])
async def test_free_shell_asks_first_in_turns_the_owner_did_not_type_or_say(
    setup, source: TurnSource
) -> None:
    gate, _, memory, calls = setup
    gate._gate.timeout_s = 0.05
    set_origin(TurnOrigin(source, automation_name="Nightly"))
    result = await gate.call("shell", {"command": "date"})
    assert not result.ok and calls == []
    assert (memory.audits[0].tier, memory.audits[0].decision) == ("ask", "timeout")


async def test_free_shell_asks_first_for_a_resident_even_in_the_owners_turn(setup) -> None:
    gate, _, memory, calls = setup
    gate._gate.timeout_s = 0.05
    set_origin(TurnOrigin("text"))
    job = gate.scoped(list(gate._tools.values()), Actor("checker", "Checker", "j1"))
    assert job.tier("shell") == "ask" and gate.tier("shell") == "free"
    assert not (await job.call("shell", {"command": "date"})).ok and calls == []


@pytest.fixture
def program_gate(config: Config) -> tuple[ToolGate, Bus, FakeMemory, list[dict[str, Any]]]:
    config.gate.tiers = {"run_program": "free", "shell": "free", "start_project": "free"}
    config.gate.timeout_s = 0.05
    bus, memory, calls = Bus(), FakeMemory(), []
    tools = [make_tool(n, calls) for n in ("run_program", "shell", "start_project")]
    return ToolGate(config, bus, memory, tools), bus, memory, calls


@pytest.mark.parametrize("via", ["text", "voice", "window"])
async def test_free_run_program_runs_without_asking_in_a_job_from_the_mac(program_gate, via: str) -> None:
    gate, bus, memory, calls = program_gate
    requests = bus.subscribe({GateRequest.TYPE})
    set_origin(TurnOrigin("phone"))  # whatever turn is current, the job's own origin decides
    job = gate.scoped(list(gate._tools.values()), Actor("maker", "Tink", "j1", "Workshop", via))
    result = await job.call("run_program", {"command": "git rev-parse HEAD"})
    assert result.ok and calls == [{"command": "git rev-parse HEAD"}]
    assert requests._queue.empty()
    [audit] = memory.audits
    assert (audit.tool, audit.tier, audit.decision, audit.request_id) == ("run_program", "free", "allow", "")
    assert (audit.agent, audit.job, audit.args) == ("maker", "j1", {"command": "git rev-parse HEAD"})


@pytest.mark.parametrize("via", ["phone", "automation", "job", "", "unknown"])
async def test_free_run_program_asks_first_in_a_job_not_from_the_mac(program_gate, via: str) -> None:
    gate, bus, memory, calls = program_gate
    requests = bus.subscribe({GateRequest.TYPE})
    set_origin(TurnOrigin("text"))
    job = gate.scoped(list(gate._tools.values()), Actor("maker", "Tink", "j1", "Workshop", via))
    result = await job.call("run_program", {"command": "git status"})
    assert not result.ok and calls == []
    request = requests._queue.get_nowait()
    assert isinstance(request, GateRequest) and request.job == "j1"
    assert (memory.audits[0].tier, memory.audits[0].decision) == ("ask", "timeout")


async def test_a_job_from_the_mac_frees_neither_shell_nor_start_project(program_gate) -> None:
    gate, _, memory, calls = program_gate
    set_origin(TurnOrigin("text"))
    job = gate.scoped(list(gate._tools.values()), Actor("maker", "Tink", "j1", None, "text"))
    assert job.tier("shell") == "ask" and job.tier("start_project") == "ask"
    assert not (await job.call("shell", {"command": "date"})).ok
    assert not (await job.call("start_project", {})).ok
    assert calls == [] and [a.decision for a in memory.audits] == ["timeout", "timeout"]


async def test_run_program_asks_for_the_host_whatever_the_turn(program_gate) -> None:
    gate, _, _, _ = program_gate
    set_origin(TurnOrigin("text"))
    assert gate.tier("run_program") == "ask"


async def test_never_and_unknown_are_refused_and_audited(setup) -> None:
    gate, _, memory, calls = setup
    assert not (await gate.call("banned", {})).ok
    assert not (await gate.call("nope", {})).ok
    assert calls == []
    assert [(a.tool, a.decision) for a in memory.audits] == [("banned", "deny"), ("nope", "deny")]


async def test_tool_failure_is_a_result_not_an_exception(config: Config) -> None:
    calls: list[dict[str, Any]] = []
    gate = ToolGate(config, Bus(), FakeMemory(), [make_tool("remember", calls, fail=True)])
    result = await gate.call("remember", {})
    assert not result.ok and result.content == "it broke"


async def test_cancelled_ask_is_resolved_and_audited(setup) -> None:
    gate, bus, memory, _ = setup
    resolved = bus.subscribe({GateResolved.TYPE})
    task = asyncio.create_task(gate.call("ask_tool", {"command": "ls"}))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert resolved._queue.get_nowait().decision == "deny"
    assert memory.audits[0].result == "cancelled"
    assert not gate.waiting
