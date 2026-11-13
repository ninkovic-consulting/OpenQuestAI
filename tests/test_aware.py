"""The assistant's awareness: the house and agents, one room, its own status, and the summary."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from settings_fakes import GOOD_KEY, FakeOutside, client, use

from vision.app import Daemon
from vision.aware import limits
from vision.aware.house_view import NoSuchRoom, find_room
from vision.aware.personas import parse
from vision.core.events import InputText, VisionReply
from vision.memory.library import library_contents
from vision.testing.fakes import FakeBrain


async def call(d: Daemon, tool: str, **args: Any) -> str:
    result = await d.components.tools.call(tool, args)
    assert result.ok, result.content
    return result.content


async def add_den(d: Daemon) -> None:
    async with client(d) as http:
        answer = await http.post("/api/house/rooms", json={"name": "Den", "agent": "maker", "at": [4, 1], "folders": ["/tmp", "/usr"]})
    assert answer.status_code == 201, answer.text


def test_a_persona_gives_role_and_character() -> None:
    persona = parse(
        "# The maker\n\nYou build things. The Kitchen is yours.\n\n"
        "**How you speak.** Cheerful and practical. You think out loud.\n\n"
        "**What you do.** You write code, sketch prototypes. More here.\n"
    )
    assert persona.role == "maker"
    assert persona.about == "You build things."
    assert persona.manner == "Cheerful and practical."
    assert persona.work == "You write code, sketch prototypes."


def test_rooms_are_found_when_said_loosely() -> None:
    plan = {"rooms": [{"id": "library", "name": "Library"}, {"id": "control-room", "name": "Control Room"}, {"id": "workshop", "name": "Workshop"}, {"id": "game-room", "name": "Game Room"}]}
    for said, room in [
        ("the library", "library"),
        ("LIBRARY", "library"),
        ("Library room", "library"),
        ("control-room", "control-room"),
        ("the control room", "control-room"),
        ("workshp", "workshop"),
        ("games room", "game-room"),
        ("game", "game-room"),
    ]:
        assert find_room(plan, said)["id"] == room, said
    with pytest.raises(NoSuchRoom) as missing:
        find_room(plan, "ballroom")
    assert "Library, Control Room, Workshop, Game Room" in str(missing.value)


async def test_the_house_overview_has_every_room_and_agent(daemon: Daemon) -> None:
    await add_den(daemon)
    text = await call(daemon, "house_overview")
    for room in ("Hall", "Library", "Control Room", "Comms Room", "Kitchen", "Workshop", "Attic", "Den"):
        assert f"- {room} (id " in text, room
    assert "1 extra" in text and "folders /tmp, /usr" in text
    assert "- Tink, the maker (id maker). Free to take work. Model claude-opus-5-5." in text
    assert "At work it keeps its own notes" in text
    assert "Wren, the envoy (id envoy)" in text and "it has no mail or messaging access yet" in text
    assert "Rooms: Kitchen, Game Room, Garage, Workshop, Den." in text
    assert "- Vision, the host (id host). This is you. Awake (idle)." in text
    assert "Manner: Cheerful and practical." in text
    assert limits.limits_line(daemon.residents.has_project_tools) in text


async def test_room_details_with_tools_and_whether_they_work(daemon: Daemon) -> None:
    await add_den(daemon)
    den = await call(daemon, "room_details", room="the den")
    assert den.startswith("Den (id den), an extra room, run by Tink, the maker: free to take work.")
    assert "Project folders: /tmp, /usr." in den
    hall = await call(daemon, "room_details", room="hall")
    assert "- Shell (shell): on this Mac; works today." in hall
    failed = await daemon.components.tools.call("room_details", {"room": "ballroom"})
    assert not failed.ok and "The rooms are:" in failed.content


async def test_the_library_room_says_what_the_notes_hold(daemon: Daemon) -> None:
    empty = await call(daemon, "room_details", room="Library")
    assert "The shared library is empty" in empty and "run by Brass, the steward" in empty
    library = daemon.config.paths.house / "library"
    (library / "projects.md").write_text("# Projects\n\nThe engine rewrite lives in ~/Projects/engine and ships in March.\n")
    (library / "about-me.md").write_text("Prefers short answers.\n")
    assert [e.title for e in library_contents(daemon.config)] == ["about me", "Projects"]
    full = await call(daemon, "room_details", room="the library")
    assert "The shared library holds 2 documents:" in full
    assert "- Projects (library/projects.md): The engine rewrite lives in ~/Projects/engine and ships in March." in full


async def test_its_own_status_tells_the_truth_and_no_secret(daemon: Daemon) -> None:
    use(daemon, FakeOutside(key=GOOD_KEY))
    text = await call(daemon, "assistant_status")
    assert "Name: Vision. App version" in text
    assert "Answering now: the scripted fake brain" in text
    assert "API key: stored." in text and GOOD_KEY not in text
    assert "Spend this month" in text and "of the $150.00 cap" in text
    assert "Phone channel (Discord): not set up (no bot token); not paired." in text
    assert "Tools that ask first: delete_automation, edit_file, remove_document, run_program, shell, start_project, write_file." in text
    assert "Residents' jobs: 0 at work, 0 waiting" in text
    assert f"Data lives in {daemon.config.paths.home}" in text
    assert "Automations: 0; none due." in text


async def test_the_new_tools_are_free_and_audited(daemon: Daemon) -> None:
    for name in ("house_overview", "room_details", "assistant_status"):
        assert daemon.config.gate.tiers[name] == "free"
    names = [s.name for s in daemon.components.tools.specs()]
    assert names[-16:] == [
        "house_overview", "room_details", "assistant_status", "hand_off", "list_jobs", "job_details", "cancel_job",
        "send_to_phone", "save_procedure", "list_procedures", "read_procedure", "remove_procedure",
        "propose_tool", "propose_change", "my_proposals", "start_project",
    ]


async def turn(d: Daemon, text: str) -> str:
    brain = d.components.brain
    assert isinstance(brain, FakeBrain)
    async with d.bus.subscribe({VisionReply.TYPE}) as replies:
        d.bus.publish(InputText(text=text))
        await asyncio.wait_for(replies.__anext__(), 10)
    return brain.sent[-1][0]


async def test_the_summary_reaches_the_model_and_follows_the_house(daemon: Daemon) -> None:
    first = await turn(daemon, "Hello")
    assert first.startswith("Hello\n\n[Where you are now")
    assert "You are Vision, the host. You orchestrate from the Hall and run no other room." in first
    assert "- Tink, the maker (claude-opus-5-5): Kitchen, Game Room, Garage, Workshop; free to take work." in first
    assert "The residents can take work: hand it off with hand_off" in first
    assert (await turn(daemon, "And again")) == "And again"
    await add_den(daemon)
    third = await turn(daemon, "Anything new?")
    assert "Kitchen, Game Room, Garage, Workshop, Den; free to take work." in third
    assert "- Project folders: Den: /tmp, /usr." in third
    assert "Project folders" not in first
    assert daemon.components.memory is not None
    system = daemon.components.memory.core()
    assert "Where you are now" not in system
