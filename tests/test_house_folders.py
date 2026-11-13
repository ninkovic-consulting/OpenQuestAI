"""A room's project folders in the house: the rules, the house file, the plan and the routes.

Every folder lives under `tmp_path`; the home-folder rule runs with `HOME`
pointed there, so nothing reads or writes the real home.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import Notice
from vision.house import GridHouse, HouseError, store
from vision.house.model import MAX_ROOM_FOLDERS
from vision.house.parse import build_layout


def folders_of(config: Config, folders: Any) -> tuple[str, ...]:
    doc = {"rooms": [{"id": "workshop", "folders": folders}]}
    return build_layout(store.read_toml(store.DEFAULT_FILE), doc, config).room("workshop").folders


def made(tmp_path: Path, *names: str) -> list[str]:
    for name in names:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return [str(tmp_path / name) for name in names]


def test_folders_are_kept_in_order_and_may_be_missing(config: Config, tmp_path: Path) -> None:
    assert folders_of(config, [" ~/Projects/shop ", str(tmp_path / "not-yet")]) == ("~/Projects/shop", str(tmp_path / "not-yet"))
    assert folders_of(config, []) == ()


@pytest.mark.parametrize(
    ("folders", "words"),
    [
        ("~/Projects/shop", "must be a list"),
        (["~/a", ""], "must be a list"),
        (["~/a", 3], "must be a list"),
        (["Projects/shop"], "must be a full path"),
        (["/"], "the disk, the home folder or a folder above it"),
        (["/a/b", "/a/b/"], "are the same folder"),
        (["/a/b", "/a/b/c"], "/a/b/c is inside /a/b"),
        (["/a/b/c", "/a/b"], "/a/b/c is inside /a/b"),
        ([f"/p{i}" for i in range(MAX_ROOM_FOLDERS + 1)], "at most 8"),
    ],
)
def test_folder_rules(config: Config, folders: Any, words: str) -> None:
    with pytest.raises(HouseError, match="folders|folder") as caught:
        folders_of(config, folders)
    assert words in str(caught.value)


def test_home_and_above_are_refused(config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / "me"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    for folder in ("~", str(home), str(tmp_path), "~/.."):
        with pytest.raises(HouseError, match="home folder"):
            folders_of(config, [folder])
    assert folders_of(config, ["~/Projects/shop"]) == ("~/Projects/shop",)


def test_the_same_folder_through_a_link_is_refused(config: Config, tmp_path: Path) -> None:
    real, = made(tmp_path, "real")
    os.symlink(real, tmp_path / "alias")
    with pytest.raises(HouseError, match="are the same folder"):
        folders_of(config, [real, str(tmp_path / "alias")])
    os.symlink(tmp_path, tmp_path / "up")
    with pytest.raises(HouseError, match="is inside"):
        folders_of(config, [real, str(tmp_path / "up")])


def test_the_old_project_key_is_an_unknown_setting(config: Config) -> None:
    doc = {"rooms": [{"id": "workshop", "project": "~/Projects/shop"}]}
    with pytest.raises(HouseError) as caught:
        build_layout(store.read_toml(store.DEFAULT_FILE), doc, config)
    assert str(caught.value) == (
        "Room 'workshop': unknown setting 'project'. Allowed: agent, at, floor, folders, id, model, name, "
        'shape, size, tools, wall. A room lists its project folders as folders = ["~/Projects/shop"].'
    )


async def test_a_house_file_with_project_falls_back_to_the_default_with_a_notice(config: Config) -> None:
    config.paths.house_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.house_file.write_text('[[rooms]]\nid = "workshop"\nproject = "~/Projects/shop"\n')
    bus = Bus()
    sub = bus.subscribe(["notice"])
    house = GridHouse(config, bus, poll_s=0.02)
    try:
        workshop = next(r for r in house.plan()["rooms"] if r["id"] == "workshop")
        assert workshop["folders"] == []
        event = await asyncio.wait_for(sub.get(), 2)
        assert isinstance(event, Notice) and event.level == "warn"
        assert "unknown setting 'project'" in event.text and 'folders = ["~/Projects/shop"]' in event.text
        assert "Using the default house until it is fixed." in event.text
    finally:
        await house.close()


# ------------------------------------------------------------ the routes


def client(d: Daemon) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=f"http://127.0.0.1:{d.port}", headers={"Authorization": f"Bearer {d.token}"})


async def test_rooms_take_folders_through_the_routes(daemon: Daemon, tmp_path: Path) -> None:
    a, b, c = made(tmp_path, "a", "b", "c")
    async with client(daemon) as http:
        plan = (await http.get("/api/house")).json()
        assert plan["max_room_folders"] == 8 and all(r["folders"] == [] for r in plan["rooms"])
        assert all("project" not in r for r in plan["rooms"])

        added = await http.post("/api/house/rooms", json={"name": "Den", "agent": "maker", "folders": [a, b]})
        assert added.status_code == 201 and added.json()["room"]["folders"] == [a, b]
        more = await http.patch("/api/house/rooms/den", json={"folders": [a, b, c]})
        assert more.status_code == 200 and more.json()["room"]["folders"] == [a, b, c]
        workshop = await http.patch("/api/house/rooms/workshop", json={"folders": [c]})
        assert workshop.json()["room"]["folders"] == [c]

        missing = await http.patch("/api/house/rooms/den", json={"folders": [a, str(tmp_path / "nowhere")]})
        assert missing.status_code == 400
        assert missing.json() == {"detail": f"Room 'Den': {tmp_path / 'nowhere'} is not a folder on this Mac, so it cannot be added to folders."}
        nested = await http.patch("/api/house/rooms/den", json={"folders": [a, f"{a}/"]})
        assert nested.status_code == 400 and "are the same folder" in nested.json()["detail"]
        old = await http.patch("/api/house/rooms/den", json={"project": a})
        assert old.status_code == 400 and "Unknown setting 'project'" in old.json()["detail"]
        shape = await http.patch("/api/house/rooms/den", json={"folders": a})
        assert shape.status_code == 400 and "folders must be a list" in shape.json()["detail"]

        os.rmdir(c)  # a folder already attached may go missing without breaking later changes
        renamed = await http.patch("/api/house/rooms/den", json={"name": "Study", "folders": [a, b, c]})
        assert renamed.status_code == 200
        cleared = await http.patch("/api/house/rooms/den", json={"folders": []})
        assert cleared.json()["room"]["folders"] == []
        workshop = await http.patch("/api/house/rooms/workshop", json={"folders": None})
        assert workshop.json()["room"]["folders"] == []

    saved = store.read_toml(daemon.config.paths.house_file)
    den = next(r for r in saved["rooms"] if r["id"] == "den")
    assert den["folders"] == [] and "project" not in den
