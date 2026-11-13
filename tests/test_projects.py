"""start_project: the safe folder name, the root, the card, what a yes makes, the full house,
failures partway, git present and absent, the first job, the agents it refuses, and that it
always asks. Every folder is a temp folder; git is a fake runner, never a real program."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from jobs_fakes import Scripted

from vision.aware import limits
from vision.core.bus import Bus
from vision.core.config import Config, load_config
from vision.core.events import GateDecision, GateRequest
from vision.gate.gate import ToolGate
from vision.gate.policy import NEVER_FREE, tier_for
from vision.gate.tools import CommandResult, Tool, ToolFailure
from vision.house import GridHouse
from vision.house.model import MAX_EXTRA_ROOMS
from vision.jobs import Board
from vision.projects import Refused, RootProblem, build_tools, folder_name, projects_root, saved_root
from vision.projects.make import carry_out
from vision.projects.names import MAX_FOLDER_NAME
from vision.projects.plan import plan_project, read_request
from vision.residents.abilities import HOST_ONLY
from vision.settings import values
from vision.testing.fakes import FakeMemory

GIT = Path("/usr/bin/git")


# ---------------------------------------------------------------- the folder name


@pytest.mark.parametrize(
    ("name", "folder"),
    [
        ("Photo Date Renamer", "photo-date-renamer"),
        ("  Café   Menu!! v2 ", "cafe-menu-v2"),
        ("../../etc/passwd", "etc-passwd"),
        ("a/b\\c", "a-b-c"),
        ("..hidden", "hidden"),
        ("Ünïcödé — Straße", "unicode-strae"),
        ("x" * 200, "x" * MAX_FOLDER_NAME),
    ],
)
def test_the_folder_name_is_safe(name: str, folder: str) -> None:
    made = folder_name(name)
    assert made == folder
    assert len(made) <= MAX_FOLDER_NAME and "/" not in made and "." not in made


def test_a_long_name_is_cut_at_a_word() -> None:
    made = folder_name("The quite remarkably long name of a project that keeps on going and going")
    assert made == "the-quite-remarkably-long-name-of-a-project-that"
    assert len(made) <= MAX_FOLDER_NAME


@pytest.mark.parametrize("name", ["", "   ", "..", "!!! ---", "日本語"])
def test_a_name_with_no_letters_or_digits_is_refused(name: str) -> None:
    with pytest.raises(Refused, match="no letters or digits"):
        folder_name(name)


# ---------------------------------------------------------------- the root


def test_the_root_must_be_an_existing_folder_of_its_own(tmp_path: Path) -> None:
    assert projects_root(str(tmp_path)) == Path(os.path.realpath(tmp_path))
    with pytest.raises(RootProblem, match="not a folder on this Mac"):
        projects_root(str(tmp_path / "missing"))
    with pytest.raises(RootProblem, match="not a full path"):
        projects_root("Projects")
    for bad in ("/", "~", str(Path.home().parent)):
        with pytest.raises(RootProblem, match="the disk, the home folder or a folder above it"):
            projects_root(bad)


def test_the_saved_root_is_read_from_config_toml(config: Config) -> None:
    assert saved_root(config) == "~/Projects"
    config.paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.config_file.write_text('[projects]\nroot = "/somewhere/else"\n')
    assert saved_root(config) == "/somewhere/else"


def test_settings_check_the_root(tmp_path: Path) -> None:
    change = values.validate({"projects": {"root": f" {tmp_path} "}}, agents=set(), tools=set())
    assert change == [("projects.root", str(tmp_path))]
    with pytest.raises(values.Invalid) as caught:
        values.validate({"projects": {"root": "/"}}, agents=set(), tools=set())
    assert caught.value.errors[0]["field"] == "projects.root"
    with pytest.raises(values.Invalid, match="not a folder on this Mac"):
        values.validate({"projects": {"root": str(tmp_path / "nope")}}, agents=set(), tools=set())
    assert values.with_change({}, change) == {"projects": {"root": str(tmp_path)}}


# ---------------------------------------------------------------- the house and the tool


@dataclass
class Rig:
    house: GridHouse
    board: Board
    work: Scripted
    tool: Tool
    root: Path
    runs: list[dict[str, Any]]
    git: list[Path | None]
    results: list[CommandResult]

    def card(self, **args: Any) -> str:
        assert self.tool.describe is not None
        return self.tool.describe(_args(**args))

    async def start(self, **args: Any) -> str:
        a = _args(**args)
        assert self.tool.describe is not None
        self.tool.describe(a)
        return await self.tool.run(a)


def _args(**args: Any) -> dict[str, Any]:
    base = {
        "name": "Photo Renamer",
        "description": "A small command-line tool that renames photos by the date they were taken.",
        "agent": "Tink",
        "reason": "It is software to build.",
    }
    return {**base, **args}


@pytest.fixture
async def rig(config: Config, tmp_path: Path) -> AsyncIterator[Rig]:
    root = tmp_path / "projects"
    root.mkdir()
    house = GridHouse(config, Bus(), poll_s=60)
    board = Board(config, Bus(), plan=house.plan, refusal=_never, light=house.set_room_state)
    work = Scripted()
    await board.start(work)
    runs: list[dict[str, Any]] = []
    git: list[Path | None] = [GIT]
    results = [CommandResult(0, "", False)]

    async def runner(argv: Sequence[str], **kw: Any) -> CommandResult:
        runs.append({"argv": list(argv), **kw})
        return results[0]

    [tool] = build_tools(lambda: house, board, lambda: str(root), finder=lambda name: git[0], runner=runner)
    yield Rig(house, board, work, tool, root, runs, git, results)
    await board.stop()
    await house.close()


async def _never() -> str | None:
    return None


def _room(house: GridHouse, room_id: str) -> dict[str, Any]:
    return next(r for r in house.plan()["rooms"] if r["id"] == room_id)


async def test_the_card_says_exactly_what_will_happen(rig: Rig) -> None:
    text = rig.card(kind="python", first_job="Write a first plan for the tool in PLAN.md.")
    folder = Path(os.path.realpath(rig.root)) / "photo-renamer"
    assert text == (
        "Project: Photo Renamer\n"
        "Description: A small command-line tool that renames photos by the date they were taken.\n"
        "Agent: Tink (maker). Why: It is software to build.\n"
        f"Folder to create: {folder}\n"
        "Inside it: README.md with the name and description, and git init (git is installed).\n"
        'Room to add: "Photo Renamer", run by Tink, at [1, -1] next to the Control Room.\n'
        "Room tools: Git, Python.\n"
        "First job for Tink, in that room:\n"
        "Write a first plan for the tool in PLAN.md."
    )
    assert not folder.exists(), "describing does nothing"


async def test_a_yes_makes_the_folder_readme_git_and_room(rig: Rig) -> None:
    said = await rig.start(kind="node")
    folder = Path(os.path.realpath(rig.root)) / "photo-renamer"
    assert (folder / "README.md").read_text() == (
        "# Photo Renamer\n\nA small command-line tool that renames photos by the date they were taken.\n"
    )
    [run] = rig.runs
    assert run["argv"] == [str(GIT), "init", "-q"] and run["cwd"] == folder
    env: Mapping[str, str] = run["env"]
    assert env["PATH"].split(":")[0] == "/usr/bin"
    assert not any(k.startswith(("VISION_", "ANTHROPIC")) for k in env)
    room = _room(rig.house, "photo-renamer")
    assert room["kind"] == "extra" and room["agent"] == "maker" and room["project"] == "Photo Renamer"
    assert room["folders"] == [f"{rig.root}/photo-renamer"] and room["at"] == [1, -1]
    assert [t["id"] for t in room["tools"]] == ["git", "npm"]
    assert said.startswith(f'Started the project "Photo Renamer" for Tink: created the folder {folder} with its README.md')
    assert "made it a git repository" in said and 'added the room "Photo Renamer"' in said
    assert "first job" not in said and rig.board.all() == []


async def test_the_first_job_goes_to_that_agent_in_the_new_room(rig: Rig) -> None:
    said = await rig.start(first_job="Write a first plan for the tool in PLAN.md.")
    [job] = rig.board.all()
    assert job.agent == "maker" and job.room == "photo-renamer" and job.asked_by == "host"
    assert job.brief == "Write a first plan for the tool in PLAN.md."
    assert f"job {job.id}" in said and "told its result in a turn of its own" in said


async def test_without_git_nothing_is_run_and_the_card_says_so(rig: Rig) -> None:
    rig.git[0] = None
    assert "No git init: git is not installed on this Mac." in rig.card()
    said = await rig.start()
    assert rig.runs == [] and "repository" not in said
    assert [t["id"] for t in _room(rig.house, "photo-renamer")["tools"]] == []


async def test_a_git_failure_is_told_and_the_rest_goes_on(rig: Rig) -> None:
    rig.results[0] = CommandResult(1, "fatal: something odd\n", False)
    said = await rig.start()
    assert "git init did not work (fatal: something odd), so the folder is not a git repository" in said
    assert _room(rig.house, "photo-renamer")["project"] == "Photo Renamer"


async def test_an_existing_folder_is_never_overwritten(rig: Rig) -> None:
    taken = rig.root / "photo-renamer"
    taken.mkdir()
    (taken / "keep.txt").write_text("mine")
    assert "already has something called photo-renamer" in rig.card()
    result = await _call(rig)
    assert not result.ok and "never goes over what exists" in result.content
    assert sorted(os.listdir(taken)) == ["keep.txt"]
    (rig.root / "link-name").symlink_to(rig.root / "elsewhere")
    result = await _call(rig, name="Link Name")
    assert not result.ok and "already has something called link-name" in result.content


async def test_a_folder_appearing_after_the_yes_is_not_overwritten(rig: Rig) -> None:
    p = plan_project(read_request(_args()), rig.house.plan(), str(rig.root), git=GIT)
    p.folder.mkdir()
    with pytest.raises(ToolFailure, match="appeared in .* before the folder could be created, so nothing was done"):
        await carry_out(p, rig.house, rig.board, runner=_unused, via="text")
    assert os.listdir(p.folder) == [] and _room_count(rig) == 0


async def _unused(argv: Sequence[str], **kw: Any) -> CommandResult:
    raise AssertionError("nothing should run")


def _room_count(rig: Rig) -> int:
    return sum(1 for r in rig.house.plan()["rooms"] if r["kind"] == "extra")


async def test_never_outside_the_root_even_through_a_symlinked_root(rig: Rig, tmp_path: Path) -> None:
    real = tmp_path / "real-projects"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real)
    [tool] = build_tools(lambda: rig.house, rig.board, lambda: str(link), finder=lambda n: None)
    args = _args(name="../../Escape/../me")
    assert tool.describe is not None
    tool.describe(args)
    await tool.run(args)
    assert os.listdir(real) == ["escape-me"]
    assert not any(p.name.startswith("escape") for p in [*tmp_path.iterdir(), *tmp_path.parent.iterdir()])
    room = next(r for r in rig.house.plan()["rooms"] if r.get("project") == "../../Escape/../me")
    assert room["folders"] == [f"{link}/escape-me"]


async def test_a_missing_root_creates_nothing_and_says_what_to_do(rig: Rig, tmp_path: Path) -> None:
    missing = tmp_path / "no-projects-yet"
    [tool] = build_tools(lambda: rig.house, rig.board, lambda: str(missing), finder=lambda n: None)
    assert tool.describe is not None
    text = tool.describe(_args())
    assert text.startswith("This cannot be done, so a yes changes nothing: The folder for new projects cannot be used:")
    assert "Where new projects go" in text and "`folder`" in text
    with pytest.raises(ToolFailure, match="Nothing was created"):
        await tool.run(_args())
    assert not missing.exists() and _room_count(rig) == 0


async def test_attaching_changes_nothing_inside_the_folder(rig: Rig, tmp_path: Path) -> None:
    mine = tmp_path / "old-app"
    mine.mkdir()
    (mine / "package.json").write_text("{}")
    before = sorted(os.listdir(mine))
    text = rig.card(name="Old App", folder=str(mine))
    assert f"Folder: {os.path.realpath(mine)}, which exists; nothing in it is created or changed." in text
    assert "git init" not in text and "Room tools: npm." in text
    said = await rig.start(name="Old App", folder=str(mine))
    assert sorted(os.listdir(mine)) == before and rig.runs == []
    assert f"attached the folder {os.path.realpath(mine)}, changing nothing in it" in said
    assert _room(rig.house, "old-app")["folders"] == [str(mine)]
    for bad in (str(tmp_path / "nowhere"), "relative/path", "/"):
        assert rig.card(name="Old App 2", folder=bad).startswith("This cannot be done")


@pytest.mark.parametrize(
    ("agent", "words"),
    [
        ("Vision", "is the host"),
        ("host", "is the host"),
        ("Bob", "no agent called 'Bob'"),
        ("", "`agent` must be non-empty text"),
    ],
)
async def test_the_host_and_unknown_agents_are_refused(rig: Rig, agent: str, words: str) -> None:
    text = rig.card(agent=agent)
    assert text.startswith("This cannot be done") and words in text
    if agent:
        assert "Tink (maker)" in text
    result = await _call(rig, agent=agent)
    assert not result.ok and words in result.content and "Nothing was created." in result.content
    assert os.listdir(rig.root) == []


async def test_any_resident_by_name_or_id(rig: Rig) -> None:
    assert "Agent: Rook (scout). Why: It is research." in rig.card(agent="scout", reason="It is research.")
    assert "Agent: Wren (envoy)." in rig.card(agent="wren")
    assert "Kind: rust, which matches none of the house's tools." in rig.card(kind="rust")
    assert "Room tools: Git, Xcode." in rig.card(kind="Swift")


async def test_a_project_name_already_held_is_refused(rig: Rig) -> None:
    await rig.house.update_room("garage", {"project": "Photo Renamer"})
    assert "The Garage already holds a project called 'Photo Renamer'" in rig.card()


async def test_when_the_house_is_full_the_agents_free_room_takes_the_project(rig: Rig) -> None:
    for i in range(MAX_EXTRA_ROOMS):
        await rig.house.add_room({"name": f"Extra {i}", "agent": "steward"})
    text = rig.card(first_job="Plan it.")
    assert (
        "Room: none can be added (the house has all its extra rooms), so the project goes into the Kitchen, "
        "Tink's room with no project yet, which takes its name, folder and tools."
    ) in text
    said = await rig.start(first_job="Plan it.")
    kitchen = _room(rig.house, "kitchen")
    assert kitchen["project"] == "Photo Renamer" and kitchen["folders"] == [f"{rig.root}/photo-renamer"]
    assert "gave it to the Kitchen" in said
    [job] = rig.board.all()
    assert job.room == "kitchen"
    # The scout's only room, the Attic, now holds a project: nowhere to go, said plainly.
    await rig.house.update_room("attic", {"project": "Sky Survey"})
    text = rig.card(name="Moths", agent="Rook")
    assert "all 20 extra rooms, and none of Rook's rooms is free of a project" in text
    assert "remove an extra room (Settings, Rooms)" in text


async def test_a_room_that_cannot_be_added_leaves_the_folder_and_says_so(rig: Rig) -> None:
    async def refuse(fields: dict[str, Any]) -> dict[str, Any]:
        from vision.house import HouseError

        raise HouseError("The disk is full.")

    rig.house.add_room = refuse  # type: ignore[method-assign]
    result = await _call(rig, first_job="Plan it.")
    folder = Path(os.path.realpath(rig.root)) / "photo-renamer"
    assert not result.ok
    assert "stopped partway: the room could not be set up (The disk is full.)" in result.content
    assert f"What exists now: created the folder {folder} with its README.md; made it a git repository." in result.content
    assert "What does not: a room holding the project, and the first job. Nothing was deleted." in result.content
    assert (folder / "README.md").is_file() and rig.board.all() == []


async def test_a_first_job_that_cannot_start_says_what_exists(rig: Rig) -> None:
    async def broke() -> str | None:
        return "The month's budget is used up."

    rig.board._refusal = broke
    result = await _call(rig, first_job="Plan it.")
    assert not result.ok and "the first job could not be handed off (The month's budget is used up.)" in result.content
    assert 'added the room "Photo Renamer"' in result.content and "Nothing was deleted." in result.content
    assert _room(rig.house, "photo-renamer")["project"] == "Photo Renamer"


async def test_a_change_after_the_card_is_refused(rig: Rig) -> None:
    a = _args()
    assert rig.tool.describe is not None
    rig.tool.describe(a)
    await rig.house.add_room({"name": "Pantry", "agent": "steward", "at": [1, -1]})
    result = await ToolGate(rig.house._config, Bus(), FakeMemory(), [rig.tool])._run(rig.tool, a)
    assert not result.ok and "changed after the owner was asked" in result.content
    assert os.listdir(rig.root) == []


# ---------------------------------------------------------------- the gate


def test_it_always_asks_and_is_the_hosts_alone(config: Config) -> None:
    assert "start_project" in NEVER_FREE and "start_project" in HOST_ONLY
    config.gate.tiers["start_project"] = "free"
    for source in ("text", "voice", "phone", "automation", None):
        assert tier_for(config.gate, "start_project", source) == "ask"  # type: ignore[arg-type]
    assert load_config().gate.tiers.get("start_project", load_config().gate.default_tier) == "ask"


async def test_the_card_reaches_the_gate_request(rig: Rig) -> None:
    bus = Bus()
    gate = ToolGate(rig.house._config, bus, FakeMemory(), [rig.tool])
    sub = bus.subscribe({GateRequest.TYPE})
    call = asyncio.create_task(gate.call("start_project", _args()))
    request = await asyncio.wait_for(sub.get(), 2)
    assert isinstance(request, GateRequest)
    assert request.summary == "Start a new project" and request.detail == rig.card()
    bus.publish(GateDecision(id=request.id, decision="allow"))
    result = await call
    assert result.ok and (rig.root / "photo-renamer" / "README.md").is_file()


async def _call(rig: Rig, **args: Any) -> Any:
    a = _args(**args)
    assert rig.tool.describe is not None
    rig.tool.describe(a)
    return await ToolGate(rig.house._config, Bus(), FakeMemory(), [rig.tool])._run(rig.tool, a)


async def test_the_daemon_offers_it_to_the_host_and_says_so(daemon: Any) -> None:
    names = [s.name for s in daemon.components.tools.specs()]
    assert "start_project" in names
    assert daemon.components.tools.tier("start_project") == "ask"
    assert "start_project" not in daemon._lent_tools()
    assert limits.projects_line() in daemon.awareness.summary()
    assert "start_project" in limits.projects_line()
