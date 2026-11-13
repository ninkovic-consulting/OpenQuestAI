"""A room's project name: the house file, the routes, finding a room by it, and what the agents read."""

from __future__ import annotations

from typing import Any

import pytest
from jobs_fakes import Spend, make_board, plan
from settings_fakes import client

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.house import HouseError, store
from vision.house.model import MAX_PROJECT_NAME
from vision.house.parse import build_layout
from vision.house.project import rooms_named
from vision.jobs import Board, JobError
from vision.residents.prompt import Setting, room_part


def project_of(config: Config, value: Any) -> str | None:
    doc = {"rooms": [{"id": "workshop", "project": value}]}
    return build_layout(store.read_toml(store.DEFAULT_FILE), doc, config).room("workshop").project


def test_a_project_name_is_kept_trimmed_and_blank_means_none(config: Config) -> None:
    assert project_of(config, "  Harbor Books ") == "Harbor Books"
    assert project_of(config, "x" * MAX_PROJECT_NAME) == "x" * MAX_PROJECT_NAME
    assert project_of(config, "   ") is None
    layout = build_layout(store.read_toml(store.DEFAULT_FILE), {}, config)
    assert all(r.project is None for r in layout.rooms)


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("x" * (MAX_PROJECT_NAME + 1), "61 characters; use at most 60"),
        ("Fit\nNutri", "one line of plain text"),
        ("Fit\tNutri", "one line of plain text"),
        ("Fit\x07", "one line of plain text"),
        ("/Users/me/shop", "looks like a folder path"),
        ("~/Projects/shop", "put folders in folders"),
        (7, "project must be text"),
    ],
)
def test_a_project_name_that_breaks_a_rule_is_refused_plainly(config: Config, value: Any, words: str) -> None:
    with pytest.raises(HouseError, match=words):
        project_of(config, value)


async def test_the_routes_take_give_and_clear_a_project_name(daemon: Daemon) -> None:
    async with client(daemon) as http:
        added = await http.post("/api/house/rooms", json={"name": "Den", "agent": "maker", "project": " Harbor Books "})
        assert added.status_code == 201 and added.json()["room"]["project"] == "Harbor Books"
        plan_now = (await http.get("/api/house")).json()["rooms"]
        assert {r["id"]: r["project"] for r in plan_now}["den"] == "Harbor Books"
        assert all(r["project"] is None for r in plan_now if r["id"] != "den")

        renamed = await http.patch("/api/house/rooms/den", json={"project": "Harbor Books API"})
        assert renamed.json()["room"]["project"] == "Harbor Books API"
        workshop = await http.patch("/api/house/rooms/workshop", json={"project": "Shop"})
        assert workshop.json()["room"]["project"] == "Shop"

        written = {t["id"]: t["project"] for t in store.read_toml(daemon.config.paths.house_file)["rooms"] if "project" in t}
        assert written == {"den": "Harbor Books API", "workshop": "Shop"}
        cleared = await http.patch("/api/house/rooms/den", json={"project": ""})
        assert cleared.status_code == 200 and cleared.json()["room"]["project"] is None
        nulled = await http.patch("/api/house/rooms/workshop", json={"project": None})
        assert nulled.json()["room"]["project"] is None
        blank = await http.post("/api/house/rooms", json={"name": "Loft", "agent": "maker", "project": ""})
        assert blank.status_code == 201 and blank.json()["room"]["project"] is None

        long = await http.patch("/api/house/rooms/den", json={"project": "x" * 61})
        line = await http.post("/api/house/rooms", json={"name": "Nook", "agent": "maker", "project": "a\nb"})
        path = await http.patch("/api/house/rooms/den", json={"project": "~/Projects/shop"})
        number = await http.patch("/api/house/rooms/den", json={"project": 4})
    assert long.status_code == 400 and "at most 60" in long.json()["detail"]
    assert line.status_code == 400 and "one line of plain text" in line.json()["detail"]
    assert path.status_code == 400 and "put folders in folders" in path.json()["detail"]
    assert number.status_code == 400 and "must be text" in number.json()["detail"]
    saved = store.read_toml(daemon.config.paths.house_file)
    assert all("project" not in t for t in saved["rooms"])


def with_projects(**by_room: str) -> dict[str, Any]:
    house = plan()
    for room in house["rooms"]:
        room["project"] = by_room.get(room["id"].replace("-", "_"))
    return house


def test_rooms_named_matches_the_whole_name_ignoring_case() -> None:
    rooms = with_projects(workshop="Harbor Books", garage="Shop")["rooms"]
    assert [r["id"] for r in rooms_named(rooms, " harbor BOOKS ")] == ["workshop"]
    assert rooms_named(rooms, "Fit") == [] and rooms_named(rooms, "  ") == []


async def test_a_job_finds_its_room_by_project_name(config: Config) -> None:
    house = with_projects(workshop="Harbor Books", garage="Shop")
    board = Board(config, Bus(), plan=lambda: house, refusal=Spend())
    await board.start(lambda job, desk: None)  # type: ignore[arg-type,return-value]
    by_project = await board.hand_off("Tock", "check it", room="harbor books")
    by_name = await board.hand_off("Tock", "check it", room="Garage")
    assert (by_project.room, by_name.room) == ("workshop", "garage")
    with pytest.raises(JobError, match="no room called 'Cafe'"):
        await board.hand_off("Tock", "check it", room="Cafe")
    with pytest.raises(JobError, match="the host's"):
        await board.hand_off("Tock", "check it", room="Hall")
    await board.stop()


async def test_a_project_name_that_two_rooms_share_names_both_rooms(config: Config) -> None:
    house = with_projects(workshop="Shop", garage="shop")
    board = Board(config, Bus(), plan=lambda: house, refusal=Spend())
    await board.start(lambda job, desk: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(JobError) as caught:
        await board.hand_off("Tink", "build it", room="SHOP")
    assert str(caught.value) == (
        "More than one room holds the project 'SHOP': the Workshop (id workshop) and the Garage (id garage). "
        "Name the room by its name or id."
    )
    assert (await board.hand_off("Tink", "build it", room="garage")).room == "garage"
    await board.stop()


async def test_the_jobs_route_finds_a_room_by_project_name(daemon: Daemon) -> None:
    async with client(daemon) as http:
        await http.patch("/api/house/rooms/workshop", json={"project": "Harbor Books"})
        made = await http.post("/api/jobs", json={"agent": "Tock", "brief": "Run the tests.", "room": "harbor books"})
    assert made.status_code == 200 and made.json()["job"]["room"] == "workshop"


def setting(project: str | None) -> Setting:
    room = {"id": "workshop", "name": "Workshop", "agent": "maker", "project": project}
    return Setting({"id": "maker", "name": "Tink"}, room)


def test_a_resident_is_told_the_project_its_room_holds() -> None:
    text = room_part(setting("Harbor Books"), [])
    assert "one of your own rooms.\nThis room holds the project Harbor Books." in text
    assert "This room holds" not in room_part(setting(None), [])
    visiting = Setting({"id": "checker", "name": "Tock"}, setting("Shop").room, host_of_room="Tink")
    assert "This room holds the project Shop." in room_part(visiting, [])


async def test_the_host_reads_each_rooms_project(daemon: Daemon) -> None:
    async with client(daemon) as http:
        await http.patch("/api/house/rooms/workshop", json={"project": "Harbor Books"})
    overview = (await daemon.components.tools.call("house_overview", {})).content
    assert "run by Tink; light dark; project Harbor Books; no project folder." in overview
    assert "(id garage): run by Tink; light dark; no project folder." in overview
    details = (await daemon.components.tools.call("room_details", {"room": "harbor books"})).content
    assert details.startswith("Workshop (id workshop)") and "Project: Harbor Books. Project folder" in details.replace("Project folders: none.", "Project folder")
    assert "Projects: Workshop: Harbor Books." in daemon.awareness.summary()
    none = (await daemon.components.tools.call("room_details", {"room": "garage"})).content
    assert "Project:" not in none
