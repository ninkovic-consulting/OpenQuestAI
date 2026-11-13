"""Proposals: agents propose tools and self-changes, only the owner's routes decide, and an
approved tool runs confined, pinned to the hash the owner approved.

Most tests use a fake `confine` that records its arguments; two at the end run the real
macOS sandbox in tmp_path. Nothing touches the network, the Keychain or the real home.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import (
    Event,
    GateDecision,
    GateRequest,
    MadeToolChanged,
    Notice,
    ProposalChanged,
)
from vision.gate.gate import Actor, ToolGate
from vision.gate.tools import Tool, ToolFailure
from vision.proposals import Context, NotFound, ProposalError, Proposals, sandbox, store
from vision.proposals.changes import REFUSED
from vision.proposals.model import KEEP_DECIDED, PER_AGENT, TOTAL, Proposal
from vision.proposals.sandbox import RunResult
from vision.settings import values
from vision.testing.fakes import FakeMemory

HOST_MODEL = ("claude-haiku-5-5", "low")


class RecordingBus(Bus):
    """A bus that also keeps every event published on it."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[Event] = []

    def publish(self, event: Event) -> None:
        self.seen.append(event)
        super().publish(event)

    def of(self, kind: type[Event]) -> list[Any]:
        return [e for e in self.seen if isinstance(e, kind)]


@dataclass
class FakeConfine:
    """Stands in for `sandbox.run_confined`: records each call and answers `result`."""

    result: RunResult = field(default_factory=lambda: RunResult(0, "42\n", False, 0.1, 0))
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, language: str, script: str, stdin: bytes, **kwargs: Any) -> RunResult:
        scratch: Path = kwargs["scratch"]
        self.calls.append(
            {"language": language, "script": script, "stdin": stdin, "scratch_existed": scratch.is_dir(), **kwargs}
        )
        return self.result


@dataclass
class World:
    bus: RecordingBus
    home: Path
    vault: Path
    memory: FakeMemory
    confine: FakeConfine
    settings_calls: list[dict[str, Any]]
    phone: list[tuple[str, str]]
    shop: Path
    blog: Path
    plan: dict[str, Any]
    problem: list[str | None]
    settings_error: list[Exception] = field(default_factory=list)
    phone_error: list[Exception] = field(default_factory=list)
    proposals: Proposals = field(init=False)

    def make(self) -> Proposals:
        async def settings(body: dict[str, Any]) -> dict[str, Any]:
            if self.settings_error:
                raise self.settings_error[0]
            self.settings_calls.append(body)
            return {}

        async def tell_phone(key: str, text: str) -> None:
            if self.phone_error:
                raise self.phone_error[0]
            self.phone.append((key, text))

        clock = itertools.count(1_000.0)
        return Proposals(
            self.bus,
            self.home,
            plan=lambda: self.plan,
            memory=self.memory,
            settings=settings,
            host_now=lambda: HOST_MODEL,
            tell_phone=tell_phone,
            confine=self.confine,
            confinement_problem=lambda: self.problem[0],
            reserved=frozenset({"shell", "remember", "run_program"}),
            clock=lambda: float(next(clock)),
        )

    @property
    def tink(self) -> Context:
        return Context("maker", "Tink", job="job1", room="workshop", folders=(("shop", self.shop), ("blog", self.blog)))

    @property
    def tink_shop_only(self) -> Context:
        return Context("maker", "Tink", job="job2", room="annex", folders=(("shop", self.shop),))

    @property
    def tock(self) -> Context:
        return Context("checker", "Tock", job="job3", room="lab", folders=(("shop", self.shop),))

    @property
    def host(self) -> Context:
        return Context("host", "Vision")


def house_plan() -> dict[str, Any]:
    return {
        "agents": [
            {"id": "host", "name": "Vision", "model": "claude-haiku-5-5", "effort": "low", "persona": "agents/host.md"},
            {"id": "maker", "name": "Tink", "model": "claude-sonnet-5", "effort": "medium", "persona": "agents/maker.md"},
            {"id": "checker", "name": "Tock", "model": "claude-opus-4-6", "effort": "medium", "persona": "agents/checker.md"},
        ],
        "rooms": [],
    }


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(tmp_path)


def build_world(tmp_path: Path) -> World:
    """A vault with two personas, two project folders, and `Proposals` on fakes."""
    root = Path(os.path.realpath(tmp_path))
    home = root / "vision-home"
    vault = home / "house"
    (vault / "agents").mkdir(parents=True)
    (vault / "agents" / "maker.md").write_text("You are Tink, the maker.\n")
    (vault / "agents" / "host.md").write_text("You are Vision.\n")
    shop, blog = root / "Projects" / "shop", root / "Projects" / "blog"
    shop.mkdir(parents=True)
    blog.mkdir(parents=True)
    (shop / "readme.txt").write_text("one\ntwo\nthree\n")
    (blog / "post.txt").write_text("secret draft\n")
    w = World(RecordingBus(), home, vault, FakeMemory(), FakeConfine(), [], [], shop, blog, house_plan(), [None])
    w.proposals = w.make()
    return w


SCRIPT = "import json, sys\nprint(len(json.load(sys.stdin)['path']))\n"


def tool_fields(**over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "name": "count_lines",
        "description": "Count the lines of a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "most": {"type": "integer"}},
            "required": ["path"],
        },
        "language": "python",
        "script": SCRIPT,
        "folders": ["shop", "blog"],
        "network": False,
        "reason": "Counting lines by hand takes many steps.",
    }
    return fields | over


async def approved_tool(w: World, *, who: str = "author", tier: str = "ask", **over: Any) -> Proposal:
    made = await w.proposals.propose_tool(w.tink, tool_fields(**over))
    return await w.proposals.approve(made.id, who, tier)


def tool_named(tools: list[Tool], name: str) -> Tool:
    return next(t for t in tools if t.spec.name == name)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ------------------------------------------------------------ proposing and limits


async def test_a_tool_proposal_waits_and_tells_the_model_plainly(world: World) -> None:
    tools = world.proposals.agent_tools(world.tink)
    assert [t.spec.name for t in tools] == ["propose_tool", "propose_change", "my_proposals"]
    answer = await tool_named(tools, "propose_tool").run(tool_fields())
    [p] = world.proposals.listing()
    assert answer == (
        f"Proposal {p.id} is waiting for the owner, who decides at the Mac. Nothing runs until then. "
        "Carry on without it."
    )
    assert p.status == "waiting" and p.title == "New tool count_lines" and p.agent_name == "Tink"
    assert p.job == "job1" and p.room == "workshop"
    assert p.tool is not None and p.tool.tool_name == "made_count_lines" and p.tool.version == 1
    assert p.tool.reach.to_dict() == {
        "folders": [{"name": "shop", "path": str(world.shop)}, {"name": "blog", "path": str(world.blog)}],
        "network": False,
    }
    assert world.proposals.tools_for(world.tink) == []
    assert world.confine.calls == []
    mine = await tool_named(tools, "my_proposals").run({})
    assert mine == f"- {p.id}, New tool count_lines: waiting for the owner."


async def test_waiting_limits_per_agent_and_in_all(world: World) -> None:
    for n in range(PER_AGENT):
        await world.proposals.propose_tool(world.tink, tool_fields(name=f"tool_{n}"))
    with pytest.raises(ProposalError) as one:
        await world.proposals.propose_tool(world.tink, tool_fields(name="tool_more"))
    assert str(one.value) == (
        "You already have 3 proposals waiting for the owner. Wait until they decide before proposing more."
    )
    for agent in range(1, TOTAL // PER_AGENT):
        ctx = Context(f"agent{agent}", f"Agent {agent}")
        for n in range(PER_AGENT):
            await world.proposals.propose_tool(ctx, tool_fields(name=f"tool_{agent}_{n}", folders=[]))
    assert world.proposals.waiting_count() == TOTAL
    with pytest.raises(ProposalError, match="The owner already has 12 proposals waiting"):
        await world.proposals.propose_tool(Context("late", "Late"), tool_fields(name="tool_late", folders=[]))
    first = world.proposals.listing()[0]
    await world.proposals.decline(first.id)
    await world.proposals.propose_tool(Context("late", "Late"), tool_fields(name="tool_late", folders=[]))


@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"name": "Count"}, "must start with a lowercase letter"),
        ({"name": "ab"}, "must start with a lowercase letter"),
        ({"name": "scratch"}, "must start with a lowercase letter"),
        ({"name": "shell"}, "built-in tool"),
        ({"name": "made_x_tool"}, "built-in tool"),
        ({"description": "x" * 201}, "description is longer than 200"),
        ({"reason": " "}, "reason is empty"),
        ({"reason": "x" * 1001}, "reason is longer than 1,000"),
        ({"input_schema": {"type": "array"}}, '"type": "object"'),
        ({"input_schema": {"type": "object", "description": "x" * 4000}}, "longer than 4,000"),
        ({"input_schema": {"type": "object", "required": "path"}}, "required must be a list"),
        ({"language": "ruby"}, "python (standard library only) or sh"),
        ({"script": "  "}, "script is empty"),
        ({"script": "x" * 20_001}, "longer than 20,000"),
        ({"folders": ["shop", "secrets"]}, "secrets is not a folder of this room. Its folders are: shop, blog."),
        ({"network": "yes"}, "network must be true or false"),
    ],
)
async def test_tool_proposals_are_checked(world: World, over: dict[str, Any], words: str) -> None:
    with pytest.raises(ProposalError, match=words.replace("(", r"\(").replace(")", r"\)")):
        await world.proposals.propose_tool(world.tink, tool_fields(**over))
    assert world.proposals.waiting_count() == 0


async def test_the_host_declares_no_folders_and_a_name_waits_only_once(world: World) -> None:
    with pytest.raises(ProposalError, match="no project folders here"):
        await world.proposals.propose_tool(world.host, tool_fields())
    schema_text = json.dumps({"type": "object", "properties": {}})
    made = await world.proposals.propose_tool(world.host, tool_fields(folders=[], input_schema=schema_text))
    assert made.tool is not None and made.tool.reach.folders == () and made.tool.input_schema["type"] == "object"
    with pytest.raises(ProposalError, match="already waiting"):
        await world.proposals.propose_tool(world.tink, tool_fields())


async def test_a_new_proposal_is_announced_in_the_window_and_on_the_phone(world: World) -> None:
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    [notice] = world.bus.of(Notice)
    assert notice.level == "info"
    assert notice.text == (
        "Tink proposes a new tool, count_lines. Look at Proposals in the window to approve or decline it."
    )
    [(key, text)] = world.phone
    assert key == f"proposal:{made.id}"
    assert "on the Mac" in text and "cannot be approved from the phone" in text
    [changed] = world.bus.of(ProposalChanged)
    assert (changed.id, changed.kind, changed.status, changed.agent, changed.waiting) == (
        made.id, "tool", "waiting", "maker", 1,
    )
    world.phone_error.append(RuntimeError("phone unreachable"))
    await world.proposals.propose_change(world.tink, "model", "claude-opus-5-5", "Harder work ahead.")
    assert world.proposals.waiting_count() == 2
    assert world.bus.of(Notice)[-1].text.startswith("Tink proposes a change to its model.")


# ------------------------------------------------------------ the store


async def test_the_store_persists_reloads_and_survives_a_broken_file(world: World) -> None:
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    path = world.home / store.FILE_NAME
    assert mode(path) == 0o600
    data = json.loads(path.read_text())
    assert data["version"] == 1 and data["proposals"][0]["tool"]["script"] == SCRIPT
    again = world.make()
    assert again.get(made.id).detail() == made.detail()
    path.write_text("{not json")
    empty = world.make()
    assert empty.listing() == [] and (world.home / "proposals.json.broken").exists()


def test_the_store_keeps_every_waiting_and_the_newest_decided() -> None:
    def proposal(n: int, status: str) -> Proposal:
        return Proposal(
            id=f"p{n}", kind="change", status=status, agent="maker", agent_name="Tink", job="", room=None,  # type: ignore[arg-type]
            title="t", reason="r", created_at=float(n), decided_at=None if status == "waiting" else float(n),
        )

    rows = [proposal(n, "declined") for n in range(KEEP_DECIDED + 5)] + [proposal(999, "waiting")]
    kept = store.pruned(rows)
    assert len(kept) == KEEP_DECIDED + 1
    assert "p999" in {p.id for p in kept} and "p0" not in {p.id for p in kept} and "p204" in {p.id for p in kept}


# ------------------------------------------------------------ only the owner's routes decide


async def test_nothing_but_the_owner_path_approves(world: World, config: Config) -> None:
    """A gate decision on the bus (what the window's card, a phone button press in
    `vision.remote.approvals.press`, and the gate's own `answer` all publish) never touches a
    proposal, and a typed or spoken yes reaches the gate's `answer`, which has no request to
    settle: the proposal waits for the owner's route."""
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    world.bus.publish(GateDecision(id=made.id, decision="allow"))
    await asyncio.sleep(0.01)
    gate = ToolGate(config, world.bus, world.memory, [], more=lambda: world.proposals.tools_for(world.host))
    assert gate.answer("yes") is False
    assert gate.answer("approve") is False
    await asyncio.sleep(0.01)
    assert world.proposals.get(made.id).status == "waiting"
    assert world.proposals.tools_for(world.tink) == []
    assert world.memory.audits == []


async def test_decisions_are_final_and_unknown_ids_are_not_found(world: World) -> None:
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    declined = await world.proposals.decline(made.id, "  Not needed now.  ")
    assert declined.status == "declined" and declined.note == "Not needed now." and declined.decided_at is not None
    with pytest.raises(ProposalError, match="already declined"):
        await world.proposals.approve(made.id)
    with pytest.raises(ProposalError, match="already declined"):
        await world.proposals.decline(made.id)
    with pytest.raises(NotFound):
        await world.proposals.approve("nope")
    [row] = world.memory.audits
    assert (row.tool, row.tier, row.decision, row.agent, row.job) == ("proposal", "owner", "deny", "maker", "job1")
    assert row.args == {
        "id": made.id, "kind": "tool", "action": "decline", "agent": "maker",
        "name": "count_lines", "version": 1, "sha256": made.tool.sha256,  # type: ignore[union-attr]
    }
    assert world.bus.of(ProposalChanged)[-1].status == "declined"
    mine = world.proposals.mine("maker")
    assert [p.id for p in mine] == [made.id]


# ------------------------------------------------------------ approving a tool


async def test_approving_a_tool_installs_it_for_the_right_agents(world: World) -> None:
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    with pytest.raises(ProposalError, match="author or everyone"):
        await world.proposals.approve(made.id, "anyone", "ask")
    with pytest.raises(ProposalError, match="asks each time"):
        await world.proposals.approve(made.id, "author", "never")
    done = await world.proposals.approve(made.id, "author", "ask")
    assert done.status == "approved" and done.decision is not None and done.decision.to_dict() == {
        "who": "author", "tier": "ask",
    }
    folder = world.home / "made-tools" / "count_lines"
    assert (folder / "versions" / "1.py").read_text() == SCRIPT
    assert mode(folder / "manifest.json") == 0o600 and mode(folder / "versions" / "1.py") == 0o600
    manifest = json.loads((folder / "manifest.json").read_text())["tool"]
    assert manifest["versions"][0]["sha256"] == done.tool.sha256  # type: ignore[union-attr]
    [offered] = world.proposals.tools_for(world.tink)
    assert offered.spec.name == "made_count_lines" and offered.tier == "ask"
    assert offered.summary == "Run the new tool count_lines"
    assert offered.spec.input_schema == tool_fields()["input_schema"]
    assert offered.spec.description.startswith("Count the lines of a file.")
    assert "Tink wrote, approved by the owner; it runs confined by macOS" in offered.spec.description
    assert offered.stamp is not None and offered.stamp() == {"sha256": done.tool.sha256, "version": "1"}  # type: ignore[union-attr]
    assert world.proposals.tools_for(world.tock) == [] and world.proposals.tools_for(world.host) == []
    await world.proposals.made_update("count_lines", who="everyone")
    assert [t.spec.name for t in world.proposals.tools_for(world.tock)] == ["made_count_lines"]
    assert [t.spec.name for t in world.proposals.tools_for(world.host)] == ["made_count_lines"]
    [row] = world.memory.audits
    assert row.decision == "allow" and row.args["action"] == "approve" and row.args["who"] == "author"
    assert row.args["sha256"] == done.tool.sha256 and row.args["version"] == 1  # type: ignore[union-attr]
    made_events = [(e.name, e.change, e.enabled) for e in world.bus.of(MadeToolChanged)]
    assert made_events == [("count_lines", "approved", True), ("count_lines", "updated", True)]
    summary = world.proposals.made_list()[0]
    assert summary["status"] == "enabled" and summary["author_name"] == "Tink" and summary["who"] == "everyone"
    assert summary["versions"] == [
        {"version": 1, "sha256": done.tool.sha256, "approved_at": summary["versions"][0]["approved_at"], "proposal": done.id},  # type: ignore[union-attr]
    ]
    reloaded = world.make()
    assert [t.spec.name for t in reloaded.tools_for(world.tock)] == ["made_count_lines"]


async def test_a_run_through_the_gate_asks_shows_input_and_reach_and_is_audited(world: World, config: Config) -> None:
    done = await approved_tool(world)
    config.gate.timeout_s = 5
    gate = ToolGate(
        config, world.bus, world.memory, [], actor=Actor("maker", "Tink", "job2", "Annex"),
        more=lambda: world.proposals.tools_for(world.tink_shop_only),
    )
    assert "made_count_lines" in [s.name for s in gate.specs()]
    requests = world.bus.subscribe({GateRequest.TYPE})
    call = asyncio.create_task(gate.call("made_count_lines", {"path": "shop/readme.txt"}))
    request = await asyncio.wait_for(requests.get(), 5)
    assert isinstance(request, GateRequest) and request.tool == "made_count_lines"
    assert request.summary == "Tink, in the Annex: run the new tool count_lines"
    assert 'Input: {"path": "shop/readme.txt"}' in request.detail
    assert f"May read: shop ({world.shop})" in request.detail and "blog" not in request.detail
    assert "Network: no" in request.detail
    assert f"Version 1, sha256 {done.tool.sha256[:12]}, written by Tink" in request.detail  # type: ignore[union-attr]
    world.bus.publish(GateDecision(id=request.id, decision="allow"))
    result = await asyncio.wait_for(call, 5)
    assert result.ok and result.content == "exit code 0\n42"
    [ran] = world.confine.calls
    assert ran["language"] == "python" and ran["script"] == SCRIPT
    assert json.loads(ran["stdin"]) == {"path": "shop/readme.txt"}
    assert ran["reach"] == sandbox.Reach(read=(world.shop,), network=False)
    assert json.loads(ran["env_extra"]["FOLDERS"]) == {"shop": str(world.shop)}
    assert ran["deny"] == [world.home] and ran["timeout"] == 30 and ran["limit"] == 20_000
    assert ran["scratch_existed"] and ran["scratch"].parent == world.home / "made-tools" / "scratch"
    assert not ran["scratch"].exists()
    audit = world.memory.audits[-1]
    assert audit.tool == "made_count_lines" and audit.decision == "allow" and audit.agent == "maker"
    assert audit.args["sha256"] == done.tool.sha256 and audit.args["version"] == "1"  # type: ignore[union-attr]
    tool = (await world.proposals.made_get("count_lines"))
    assert tool["tool"]["runs"] == 1 and tool["tool"]["last_run"]["ok"] is True
    [run] = tool["runs"]
    assert run["agent"] == "maker" and run["job"] == "job2" and run["exit_code"] == 0 and run["output"] == "42\n"
    assert tool["tool"]["script"] == SCRIPT and tool["tool"]["versions"][0]["script"] == SCRIPT
    assert world.bus.of(MadeToolChanged)[-1].change == "ran"


async def test_a_free_tool_runs_without_a_card(world: World, config: Config) -> None:
    await approved_tool(world, tier="free")
    gate = ToolGate(config, world.bus, world.memory, [], more=lambda: world.proposals.tools_for(world.tink))
    result = await asyncio.wait_for(gate.call("made_count_lines", {"path": "x"}), 5)
    assert result.ok and world.bus.of(GateRequest) == []
    assert world.memory.audits[-1].tier == "free"


async def test_reach_is_never_wider_than_the_room(world: World) -> None:
    await approved_tool(world, who="everyone", tier="free")
    for ctx, expected in (
        (world.tink, {"shop": str(world.shop), "blog": str(world.blog)}),
        (world.tink_shop_only, {"shop": str(world.shop)}),
        (world.host, {}),
    ):
        tool = tool_named(world.proposals.tools_for(ctx), "made_count_lines")
        await tool.run({"path": "x"})
        ran = world.confine.calls[-1]
        assert json.loads(ran["env_extra"]["FOLDERS"]) == expected
        assert {str(p) for p in ran["reach"].read} == set(expected.values())
    host_tool = tool_named(world.proposals.tools_for(world.host), "made_count_lines")
    assert host_tool.describe is not None
    assert "May read: nothing outside its scratch folder" in host_tool.describe({"path": "x"})


@pytest.mark.parametrize(
    ("args", "words"),
    [
        ({}, "lacks path"),
        ({"path": 3}, "path must be of type string"),
        ({"path": "x", "most": True}, "most must be of type integer"),
        ({"path": "x" * 32_001}, "longer than 32,000"),
    ],
)
async def test_input_is_checked_against_the_approved_schema(world: World, args: dict[str, Any], words: str) -> None:
    await approved_tool(world, tier="free")
    tool = tool_named(world.proposals.tools_for(world.tink), "made_count_lines")
    with pytest.raises(ToolFailure, match=words):
        await tool.run(args)
    assert world.confine.calls == []


async def test_answers_for_a_timeout_and_a_failing_exit(world: World) -> None:
    await approved_tool(world, tier="free")
    tool = tool_named(world.proposals.tools_for(world.tink), "made_count_lines")
    world.confine.result = RunResult(None, "partial", False, 30.0, 1)
    with pytest.raises(ToolFailure, match="did not finish within 30 seconds and was stopped.\npartial"):
        await tool.run({"path": "x"})
    world.confine.result = RunResult(2, "boom", True, 0.2, 0)
    with pytest.raises(ToolFailure) as failed:
        await tool.run({"path": "x"})
    assert str(failed.value) == "exit code 2\nboom\n[output truncated]"
    runs = (await world.proposals.made_get("count_lines"))["runs"]
    assert [(r["exit_code"], r["swept"], r["truncated"]) for r in runs] == [(2, 0, True), (None, 1, False)]


async def test_a_run_is_refused_when_macos_cannot_confine_it(world: World) -> None:
    await approved_tool(world, tier="free")
    tool = tool_named(world.proposals.tools_for(world.tink), "made_count_lines")
    world.problem[0] = "This Mac has no /usr/bin/sandbox-exec."
    with pytest.raises(ToolFailure, match="no /usr/bin/sandbox-exec. The tool count_lines did not run."):
        await tool.run({"path": "x"})
    assert world.confine.calls == []
    assert world.proposals.confinement() == {
        "available": False,
        "reason": "This Mac has no /usr/bin/sandbox-exec.",
        "enforced": list(sandbox.ENFORCED),
        "not_enforced": list(sandbox.NOT_ENFORCED),
    }


# ------------------------------------------------------------ the hash pin and versions


async def test_a_script_changed_on_disk_turns_the_tool_off(world: World) -> None:
    await approved_tool(world, tier="free")
    tool = tool_named(world.proposals.tools_for(world.tink), "made_count_lines")
    version_file = world.home / "made-tools" / "count_lines" / "versions" / "1.py"
    version_file.write_text(SCRIPT + "import os\n")
    with pytest.raises(ToolFailure, match="changed on disk since the owner approved it"):
        await tool.run({"path": "x"})
    assert world.confine.calls == []
    assert world.proposals.tools_for(world.tink) == []
    world.proposals.tools_for(world.tink)
    disabled = [e for e in world.bus.of(MadeToolChanged) if e.change == "disabled"]
    warns = [n for n in world.bus.of(Notice) if n.level == "warn"]
    assert len(disabled) == 1 and len(warns) == 1 and "count_lines changed on disk" in warns[0].text
    summary = world.proposals.made_list()[0]
    assert summary["status"] == "changed" and summary["enabled"] is False and "changed on disk" in summary["disabled_reason"]
    with pytest.raises(ProposalError, match="cannot be turned on. Go back to an approved version"):
        await world.proposals.made_update("count_lines", enabled=True)
    with pytest.raises(ProposalError, match="no longer matches"):
        await world.proposals.made_use_version("count_lines", 1)
    assert world.make().made_list()[0]["status"] == "changed"


async def test_listing_notices_an_edit_and_going_back_to_a_version_works(world: World) -> None:
    await approved_tool(world, tier="free")
    second = await world.proposals.propose_tool(world.tink, tool_fields(script=SCRIPT + "# v2\n"))
    await world.proposals.approve(second.id, "author", "free")
    v2 = world.home / "made-tools" / "count_lines" / "versions" / "2.py"
    assert [t.stamp() for t in world.proposals.tools_for(world.tink) if t.stamp] == [
        {"sha256": second.tool.sha256, "version": "2"},  # type: ignore[union-attr]
    ]
    v2.write_text("print('not what you approved')\n")
    assert world.proposals.tools_for(world.tink) == []
    with pytest.raises(NotFound):
        await world.proposals.made_use_version("count_lines", 9)
    back = await world.proposals.made_use_version("count_lines", 1)
    assert back["version"] == 1 and back["status"] == "enabled"
    [tool] = world.proposals.tools_for(world.tink)
    assert tool.stamp is not None and tool.stamp()["version"] == "1"
    await tool.run({"path": "x"})
    assert world.confine.calls[-1]["script"] == SCRIPT


async def test_a_new_version_waits_disabled_and_decline_puts_the_tool_back(world: World) -> None:
    first = await approved_tool(world, tier="free")
    with pytest.raises(ProposalError, match="count_lines is Tink's tool; only Tink or the host"):
        await world.proposals.propose_tool(world.tock, tool_fields(folders=["shop"]))
    second = await world.proposals.propose_tool(world.tink, tool_fields(script=SCRIPT + "# v2\n"))
    assert second.title == "New version 2 of count_lines"
    assert second.tool is not None and second.tool.version == 2 and second.tool.replaces == 1
    assert world.bus.of(Notice)[-1].text.startswith("Tink proposes version 2 of the tool count_lines.")
    summary = world.proposals.made_list()[0]
    assert summary["status"] == "pending" and summary["enabled"] is False and summary["version"] == 1
    assert world.proposals.tools_for(world.tink) == []
    with pytest.raises(ProposalError, match="waits for your decision"):
        await world.proposals.made_update("count_lines", enabled=True)
    with pytest.raises(ProposalError, match="waits for your decision"):
        await world.proposals.made_use_version("count_lines", 1)
    await world.proposals.decline(second.id, "Keep the first.")
    assert world.proposals.made_list()[0]["status"] == "enabled"
    assert [t.stamp() for t in world.proposals.tools_for(world.tink) if t.stamp] == [
        {"sha256": first.tool.sha256, "version": "1"},  # type: ignore[union-attr]
    ]
    events = [(e.change, e.enabled) for e in world.bus.of(MadeToolChanged)]
    assert events == [("approved", True), ("disabled", False), ("enabled", True)]
    third = await world.proposals.propose_tool(world.host, tool_fields(script=SCRIPT + "# v2 again\n", folders=[]))
    assert third.tool is not None and third.tool.version == 2
    await world.proposals.approve(third.id, "everyone", "ask")
    summary = world.proposals.made_list()[0]
    assert summary["version"] == 2 and [v["version"] for v in summary["versions"]] == [1, 2]
    assert summary["tier"] == "ask" and summary["who"] == "everyone" and summary["author"] == "maker"
    assert summary["reach"] == {"folders": [], "network": False}
    versions = world.home / "made-tools" / "count_lines" / "versions"
    assert (versions / "1.py").read_text() == SCRIPT and (versions / "2.py").read_text() == SCRIPT + "# v2 again\n"


async def test_declining_a_new_version_of_a_disabled_tool_leaves_it_off(world: World) -> None:
    await approved_tool(world)
    off = await world.proposals.made_update("count_lines", enabled=False)
    assert off["status"] == "disabled" and off["disabled_reason"] == "You turned it off."
    second = await world.proposals.propose_tool(world.tink, tool_fields(script=SCRIPT + "# v2\n"))
    await world.proposals.decline(second.id)
    assert world.proposals.made_list()[0]["status"] == "disabled"
    on = await world.proposals.made_update("count_lines", enabled=True, tier="free")
    assert on["status"] == "enabled" and on["tier"] == "free"


async def test_deleting_a_tool_removes_its_folder(world: World) -> None:
    await approved_tool(world)
    await world.proposals.made_delete("count_lines")
    assert not (world.home / "made-tools" / "count_lines").exists()
    assert world.proposals.made_list() == [] and world.proposals.tools_for(world.tink) == []
    assert world.bus.of(MadeToolChanged)[-1].change == "deleted"
    with pytest.raises(NotFound):
        await world.proposals.made_delete("count_lines")
    with pytest.raises(NotFound):
        await world.proposals.made_get("count_lines")


# ------------------------------------------------------------ self-changes


FORBIDDEN = [
    "tier", "tiers", "gate", "budget", "cap_usd", "phone_tools", "key", "api_key", "heavy_model", "name",
    "tools", "folders", "code", "heavy_effort", "",
]


@pytest.mark.parametrize("name", FORBIDDEN)
async def test_only_persona_model_and_effort_can_be_proposed(world: World, name: str) -> None:
    with pytest.raises(ProposalError) as refused:
        await world.proposals.propose_change(world.tink, name, "anything", "Because.")
    assert str(refused.value) == REFUSED
    with pytest.raises(ProposalError) as again:
        await world.proposals.propose_change(world.host, name, "anything", "Because.", agent="maker")
    assert str(again.value) == REFUSED
    assert world.proposals.waiting_count() == 0


async def test_who_may_propose_a_change_for_whom(world: World) -> None:
    with pytest.raises(ProposalError, match="only to yourself"):
        await world.proposals.propose_change(world.tink, "model", "claude-opus-5-5", "Faster.", agent="checker")
    with pytest.raises(ProposalError, match="There is no agent called nobody"):
        await world.proposals.propose_change(world.host, "model", "claude-opus-5-5", "Faster.", agent="nobody")
    made = await world.proposals.propose_change(world.host, "effort", "high", "Tink works on hard code.", agent="Tink")
    assert made.change is not None and made.change.agent == "maker" and made.change.before == "medium"
    assert made.agent == "host" and made.title == "Tink's thinking level"
    assert world.bus.of(Notice)[-1].text.startswith("Vision proposes a change to Tink's thinking level.")
    with pytest.raises(ProposalError, match="already waiting"):
        await world.proposals.propose_change(world.tink, "effort", "max", "Even harder.")


@pytest.mark.parametrize(
    ("ctx", "name", "value", "words"),
    [
        ("tink", "model", "claude-sonnet-5", "That is already Tink's model."),
        ("tink", "effort", "medium", "That is already Tink's thinking level."),
        ("host", "model", "claude-haiku-5-5", "That is already Vision's model."),
        ("tink", "persona", "You are Tink, the maker.\n", "That is already Tink's persona."),
        ("tink", "persona", "   ", "The new persona is empty."),
        ("tink", "persona", "x" * 8001, "longer than 8,000"),
        ("tink", "effort", "extreme", "A thinking level is one of"),
        ("tink", "model", "rm -rf /", "That is not a model name."),
        ("tock", "effort", "xhigh", "claude-opus-4-6 does not take effort xhigh"),
    ],
)
async def test_change_values_are_checked(world: World, ctx: str, name: str, value: str, words: str) -> None:
    with pytest.raises(ProposalError, match=words.replace("(", r"\(")):
        await world.proposals.propose_change(getattr(world, ctx), name, value, "Because.")


async def test_a_persona_change_is_applied_and_put_back(world: World) -> None:
    persona = world.vault / "agents" / "maker.md"
    made = await world.proposals.propose_change(world.tink, "persona", "You are Tink. Be brief.\n", "Shorter answers.")
    assert made.change is not None and made.change.before == "You are Tink, the maker.\n"
    done = await world.proposals.approve(made.id)
    assert persona.read_text() == "You are Tink. Be brief.\n" and done.decision is None
    assert world.settings_calls == []
    restored = await world.proposals.restore(made.id)
    assert persona.read_text() == "You are Tink, the maker.\n" and restored.restored_at is not None
    with pytest.raises(ProposalError, match="already put back"):
        await world.proposals.restore(made.id)
    assert [(a.args["action"], a.decision, a.args["field"], a.args["for"]) for a in world.memory.audits] == [
        ("approve", "allow", "persona", "maker"),
        ("restore", "allow", "persona", "maker"),
    ]
    assert [e.status for e in world.bus.of(ProposalChanged)] == ["waiting", "approved", "approved"]
    assert "later put back" in (await tool_named(world.proposals.agent_tools(world.tink), "my_proposals").run({}))


async def test_a_persona_outside_the_vault_is_refused(world: World) -> None:
    world.plan["agents"][1]["persona"] = "../../outside.md"
    with pytest.raises(ProposalError, match="outside the vault"):
        await world.proposals.propose_change(world.tink, "persona", "New.", "Because.")


async def test_model_and_effort_go_through_settings(world: World) -> None:
    model = await world.proposals.propose_change(world.tink, "model", "claude-opus-5-5", "Harder work.")
    host_effort = await world.proposals.propose_change(world.host, "effort", "high", "Think more.")
    host_model = await world.proposals.propose_change(world.host, "model", "claude-opus-5-5", "Smarter talk.")
    assert host_effort.change is not None and host_effort.change.before == "low"
    for p in (model, host_effort, host_model):
        await world.proposals.approve(p.id)
    await world.proposals.restore(model.id)
    assert world.settings_calls == [
        {"agents": {"maker": {"model": "claude-opus-5-5"}}},
        {"models": {"talk_effort": "high"}},
        {"models": {"talk": "claude-opus-5-5"}},
        {"agents": {"maker": {"model": "claude-sonnet-5"}}},
    ]


async def test_a_refused_change_keeps_the_proposal_waiting(world: World) -> None:
    made = await world.proposals.propose_change(world.tink, "model", "claude-unknown-1", "Try it.")
    world.settings_error.append(values.Invalid([{"field": "agents", "message": "claude-unknown-1 is not a model."}]))
    with pytest.raises(ProposalError, match="claude-unknown-1 is not a model."):
        await world.proposals.approve(made.id)
    assert world.proposals.get(made.id).status == "waiting"
    assert world.memory.audits == [] and [e.status for e in world.bus.of(ProposalChanged)] == ["waiting"]
    world.settings_error[:] = [RuntimeError("disk full")]
    with pytest.raises(ProposalError, match="Settings failed"):
        await world.proposals.approve(made.id)
    world.settings_error.clear()
    assert (await world.proposals.approve(made.id)).status == "approved"
    assert world.settings_calls == [{"agents": {"maker": {"model": "claude-unknown-1"}}}]


async def test_effort_is_checked_against_the_model_at_approval(world: World) -> None:
    made = await world.proposals.propose_change(world.tink, "effort", "xhigh", "Hard problems.")
    world.plan["agents"][1]["model"] = "claude-opus-4-6"
    with pytest.raises(ProposalError, match="does not take effort xhigh"):
        await world.proposals.approve(made.id)
    assert world.proposals.get(made.id).status == "waiting" and world.settings_calls == []


async def test_the_change_tool_answers_and_refuses_for_the_model(world: World) -> None:
    host_tools = world.proposals.agent_tools(world.host)
    resident_tools = world.proposals.agent_tools(world.tink)
    host_change = tool_named(host_tools, "propose_change")
    assert "agent" in host_change.spec.input_schema["properties"]
    assert "agent" not in tool_named(resident_tools, "propose_change").spec.input_schema["properties"]
    answer = await host_change.run({"field": "model", "value": "claude-opus-5-5", "reason": "Why not.", "agent": "Tink"})
    assert "is waiting for the owner, who decides at the Mac. Nothing changes until then." in answer
    with pytest.raises(ToolFailure) as refused:
        await tool_named(resident_tools, "propose_change").run({"field": "budget", "value": "100", "reason": "More."})
    assert str(refused.value) == REFUSED


# ------------------------------------------------------------ the real sandbox


real_sandbox = pytest.mark.skipif(
    sandbox.problem() is not None, reason=f"confinement unavailable: {sandbox.problem()}"
)

READ_BOTH = """\
import json, os, sys
folders = json.loads(os.environ["FOLDERS"])
args = json.load(sys.stdin)
for name, path in [("shop", "/SHOP/readme.txt"), ("blog", "/BLOG/post.txt")]:
    try:
        lines = len(open(path).read().splitlines())
        print(name, lines)
    except OSError:
        print(name, "denied")
print(sorted(folders), args["path"], os.getcwd() == os.environ["HOME"])
"""


@real_sandbox
async def test_end_to_end_with_the_real_sandbox(world: World) -> None:
    world.confine = sandbox.run_confined  # type: ignore[assignment]
    world.proposals = world.make()
    script = READ_BOTH.replace("/SHOP", str(world.shop)).replace("/BLOG", str(world.blog))
    await approved_tool(world, tier="free", script=script)
    tool = tool_named(world.proposals.tools_for(world.tink_shop_only), "made_count_lines")
    answer = await tool.run({"path": "readme.txt"})
    assert answer == "exit code 0\nshop 3\nblog denied\n['shop'] readme.txt True"
    assert list((world.home / "made-tools" / "scratch").iterdir()) == []


@real_sandbox
async def test_the_real_sandbox_keeps_a_script_out_of_the_assistants_home(world: World) -> None:
    world.confine = sandbox.run_confined  # type: ignore[assignment]
    world.proposals = world.make()
    secret = world.home / "proposals.json"
    script = f"cat {secret} >/dev/null 2>&1 && echo read || echo denied; echo x > note && echo wrote"
    await approved_tool(world, tier="free", language="sh", script=script, folders=[])
    tool = tool_named(world.proposals.tools_for(world.tink), "made_count_lines")
    assert await tool.run({"path": "x"}) == "exit code 0\ndenied\nwrote"
