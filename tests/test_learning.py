"""Agents that learn and extend themselves, wired into the daemon: the host's tools and context,
a resident's job (its procedures, its proposal tools, a made tool with no more reach than the
room), the real settings path for a self-change, the phone's refusal, and what the model is told.

The made tools run on a fake `confine` that records its arguments; the real sandbox is proved in
`test_proposals_sandbox.py`. No network, no Keychain, no real home.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from jobs_fakes import plan
from scheduler_fakes import until
from settings_fakes import client
from test_residents import Client, Probe, message, offered, text

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import GateDecision, GateRequest
from vision.gate.gate import Actor, JobHooks, ToolGate
from vision.house import seed_personas
from vision.jobs import Board, Job
from vision.memory.log import Log
from vision.procedures import Procedures
from vision.proposals import Context, ProposalError, Proposals
from vision.proposals.sandbox import Reach, RunResult
from vision.remote.link import Link
from vision.remote.store import PhoneState
from vision.residents import Residents
from vision.settings import values
from vision.testing.fakes import FakeBudget, FakeMemory

COUNT = {
    "name": "count_lines",
    "description": "Counts lines per file type in the project folders it may read.",
    "input_schema": {"type": "object", "properties": {"top": {"type": "integer"}}},
    "language": "python",
    "script": "import json, os, sys\nprint(json.load(sys.stdin), json.loads(os.environ['FOLDERS']))\n",
    "reason": "I count lines by hand in every review.",
}


def call(tool: str, **args: Any) -> Any:
    """The model calls `tool` (its arguments may include `name`, which `use` takes for itself)."""
    return message([{"type": "tool_use", "id": f"tu_{tool}", "name": tool, "input": args}], "tool_use")


class Recorder:
    """A fake `confine`: what each run was given."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, language: str, script: str, stdin: bytes, **kw: Any) -> RunResult:
        self.calls.append({"language": language, "script": script, "stdin": stdin, **kw})
        return RunResult(0, "42 lines", False, 0.1, 0)


class Settings:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]) -> None:
        self.bodies.append(body)


def proposals_for(config: Config, bus: Bus, house: dict[str, Any], confine: Recorder) -> Proposals:
    return Proposals(
        bus,
        config.paths.home,
        vault=config.paths.house,
        plan=lambda: house,
        memory=FakeMemory(),
        settings=Settings(),
        host_now=lambda: ("claude-haiku-5-5", "low"),
        confine=confine,
        confinement_problem=lambda: None,
    )


class Works:
    """A board and residents on the default plan, with procedures and proposals."""

    def __init__(self, config: Config, replies: list[Any], folders: list[Path]) -> None:
        self.bus = Bus()
        self.memory = FakeMemory()
        self.plan = plan([str(f) for f in folders])
        self.client = Client(replies)
        self.confine = Recorder()
        self.procedures = Procedures(config.paths.house)
        self.proposals = proposals_for(config, self.bus, self.plan, self.confine)
        root = ToolGate(config, self.bus, self.memory, [])

        async def give() -> Any:
            return self.client

        def scope(tools: Any, actor: Actor, hooks: JobHooks) -> ToolGate:
            return root.scoped(tools, actor, hooks)

        self.residents = Residents(
            config,
            plan=lambda: self.plan,
            budget=lambda: FakeBudget.from_config(config),
            client=give,
            scope=scope,
            host_tools={},
            project_tools=None,
            probe=Probe(),
            finder=lambda program: Path(sys.executable) if program.startswith("python") else None,
            procedures=self.procedures,
            proposals=self.proposals,
        )
        self.board = Board(config, self.bus, plan=lambda: self.plan, refusal=self.residents.refusal)

    async def run(self, agent: str, brief: str) -> Job:
        await self.board.start(self.residents)
        job = await self.board.hand_off(agent, brief)
        await until(lambda: not job.open, timeout=10)
        return job


@pytest.fixture
def seeded(config: Config) -> Config:
    seed_personas(config)
    return config


async def test_a_resident_saves_a_procedure_and_finds_it_next_time(seeded: Config) -> None:
    first = Works(
        seeded,
        [
            call("save_procedure", name="Check a release", when="Before a release of the shop.", steps="1. Run the tests."),
            text("Done, and noted how."),
        ],
        [],
    )
    await first.run("Tink", "Check the release.")
    tools = offered(first.client.requests[0])
    assert {"save_procedure", "list_procedures", "read_procedure", "remove_procedure"} <= set(tools)
    assert {"propose_tool", "propose_change", "my_proposals"} <= set(tools)
    assert "# Your procedures" in first.client.requests[0]["system"][0]["text"]
    assert "None yet." in first.client.requests[0]["system"][0]["text"]
    assert (seeded.paths.house / "agents" / "maker" / "procedures" / "check-a-release.md").is_file()

    second = Works(seeded, [call("read_procedure", name="check a release"), text("Followed it.")], [])
    await second.run("Tink", "Check the next release.")
    system = second.client.requests[0]["system"][0]["text"]
    assert "- Check a release: Before a release of the shop." in system
    result = second.client.requests[1]["messages"][-1]["content"][0]["content"]
    assert "1. Run the tests." in result
    assert second.procedures.read("maker", "check-a-release").opened == 2


async def test_a_made_tool_never_reaches_past_the_room(seeded: Config, tmp_path: Path) -> None:
    shop, api = tmp_path / "shop", tmp_path / "api"
    shop.mkdir(), api.mkdir()
    works = Works(seeded, [call("made_count_lines", top=3), text("42 lines.")], [shop])
    wide = Context("maker", "Tink", "j1", "workshop", (("shop", shop), ("api", api)))
    proposal = await works.proposals.propose_tool(wide, {**COUNT, "folders": ["shop", "api"]})
    await works.proposals.approve(proposal.id)

    async def answer() -> None:
        async with works.bus.subscribe({GateRequest.TYPE}) as sub:
            async for event in sub:
                assert isinstance(event, GateRequest)
                assert event.tool == "made_count_lines" and "shop" in event.detail
                works.bus.publish(GateDecision(id=event.id, decision="allow"))
                return

    answering = asyncio.create_task(answer())
    job = await works.run("Tink", "Count the lines.")
    await answering
    assert job.status == "done" and "made_count_lines" in offered(works.client.requests[0])
    [run] = works.confine.calls
    assert run["reach"] == Reach((shop.resolve(),), False)
    assert '"api"' not in run["env_extra"]["FOLDERS"] and '"shop"' in run["env_extra"]["FOLDERS"]
    audit = next(a for a in works.memory.audits if a.tool == "made_count_lines")
    assert audit.decision == "allow" and audit.args["sha256"] == proposal.tool.sha256  # type: ignore[union-attr]
    assert works.proposals.tools_for(Context("host", "Vision")) == []  # approved for its author only


async def test_the_host_gets_its_tools_and_made_tools_come_and_go(daemon: Daemon, tmp_path: Path) -> None:
    names = {s.name for s in daemon.components.tools.specs()}
    assert {"save_procedure", "propose_tool", "propose_change", "my_proposals"} <= names
    assert not any(n.startswith("made_") for n in names)
    ctx = Context("maker", "Tink", "j1", "workshop", ())
    proposal = await daemon.proposals.propose_tool(ctx, COUNT)
    await daemon.proposals.approve(proposal.id, who="everyone")
    assert "made_count_lines" in {s.name for s in daemon.components.tools.specs()}
    await daemon.proposals.made_update("count_lines", enabled=False)
    assert "made_count_lines" not in {s.name for s in daemon.components.tools.specs()}


async def test_the_host_is_told_the_truth(daemon: Daemon) -> None:
    daemon.procedures.save("host", "Morning brief", "When the owner asks for the day.", "1. Read the calendar.")
    said = daemon.surroundings()
    assert "Every agent, you included, keeps written procedures" in said
    assert "a yes in the conversation, by voice or from the phone does not approve it" in said
    assert "never look for another route to the same thing" in said
    assert "Nobody can change the approval rules, their own permissions, spending caps, keys" in said
    assert "- Morning brief: When the owner asks for the day." in said
    assert "No proposal waits for the owner." in said
    await daemon.proposals.propose_change(
        Context("maker", "Tink"), "effort", "high", "Reviews need more thought."
    )
    assert "1 proposal from the agents waits for the owner in Proposals" in daemon.surroundings()


async def test_a_self_change_goes_through_the_real_settings(daemon: Daemon) -> None:
    before = next(a for a in daemon.components.house.plan()["agents"] if a["id"] == "maker")["model"]
    after = "claude-sonnet-5-5" if before != "claude-sonnet-5-5" else "claude-haiku-5-5"
    proposal = await daemon.proposals.propose_change(Context("maker", "Tink"), "model", after, "Cheaper for small jobs.")
    async with client(daemon) as http:
        approved = await http.post(f"/api/proposals/{proposal.id}/approve", json={})
        assert approved.status_code == 200, approved.text
        assert approved.json()["proposal"]["status"] == "approved"
        agents = {a["id"]: a for a in daemon.components.house.plan()["agents"]}
        assert agents["maker"]["model"] == after
        put_back = await http.post(f"/api/proposals/{proposal.id}/restore")
        assert put_back.status_code == 200 and put_back.json()["proposal"]["restored_at"]
    agents = {a["id"]: a for a in daemon.components.house.plan()["agents"]}
    assert agents["maker"]["model"] == before
    log = Log(daemon.config.paths.log_db)
    log.open()
    audits = [a for a in log.audits() if a.tool == "proposal"]
    log.close()
    assert [a.args["action"] for a in audits] == ["approve", "restore"]


async def test_an_invalid_change_is_refused_by_settings_and_stays_waiting(daemon: Daemon) -> None:
    proposal = await daemon.proposals.propose_change(
        Context("maker", "Tink"), "effort", "max", "Think harder."
    )
    async with client(daemon) as http:
        daemon.app.state.settings.patch = _refuse  # settings refuses the value at approval time
        refused = await http.post(f"/api/proposals/{proposal.id}/approve", json={})
    assert refused.status_code == 400 and "no." in refused.json()["detail"]
    assert daemon.proposals.get(proposal.id).status == "waiting"


async def _refuse(body: dict[str, Any]) -> None:
    raise values.Invalid([{"field": "agents.maker.effort", "message": "no."}])


async def test_a_misspelt_model_is_refused_when_proposed(daemon: Daemon) -> None:
    with pytest.raises(ProposalError, match="not a model this assistant knows"):
        await daemon.proposals.propose_change(Context("maker", "Tink"), "model", "claude-sonet-5-5", "Typo.")


async def test_the_routes_are_mounted_behind_the_token(daemon: Daemon) -> None:
    async with client(daemon, token=False) as http:
        for path in ("/api/proposals", "/api/made-tools", "/api/procedures"):
            assert (await http.get(path)).status_code == 401
    async with client(daemon) as http:
        assert (await http.get("/api/proposals")).json()["waiting"] == 0
        assert "confinement" in (await http.get("/api/made-tools")).json()
        listing = (await http.get("/api/procedures")).json()
        assert {a["id"] for a in listing["agents"]} >= {"host", "maker"}


def test_the_phone_never_approves_a_made_tool() -> None:
    state = PhoneState(phone_tools=["made_count_lines", "write_file"])
    link = Link(None, None, lambda: state, None, lambda: None)  # type: ignore[arg-type]
    assert link.phone_may_approve("write_file")
    assert not link.phone_may_approve("made_count_lines")
    default = Link(None, None, lambda: PhoneState(), None, lambda: None)  # type: ignore[arg-type]
    assert not default.phone_may_approve("made_count_lines")


async def test_the_made_tools_folders_are_private(seeded: Config) -> None:
    works = Works(seeded, [], [])
    proposal = await works.proposals.propose_tool(Context("maker", "Tink"), COUNT)
    await works.proposals.approve(proposal.id)
    shelf = seeded.paths.home / "made-tools"
    for folder in (shelf, shelf / "count_lines", shelf / "count_lines" / "versions"):
        assert folder.stat().st_mode & 0o777 == 0o700, folder
