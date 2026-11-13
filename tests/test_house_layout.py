"""Merging and validating the house files (spec 4.8 rules), without the service."""

from pathlib import Path
from typing import Any

import pytest

from vision.core.config import Config
from vision.house import grid, store
from vision.house.model import HALL, TEXTURES, HouseError, Layout
from vision.house.parse import build_layout, slugify

REPO = Path(__file__).resolve().parents[1]
DEFAULT_IDS = [
    "hall",
    "library",
    "control-room",
    "comms-room",
    "kitchen",
    "game-room",
    "garage",
    "workshop",
    "spare-room",
    "attic",
]


def default_doc() -> dict[str, Any]:
    return store.read_toml(store.DEFAULT_FILE)


def layout(config: Config, *extras: dict[str, Any], **user: Any) -> Layout:
    doc: dict[str, Any] = {**user}
    if extras:
        doc["rooms"] = [*doc.get("rooms", []), *extras]
    return build_layout(default_doc(), doc, config)


def refused(config: Config, match: str, *extras: dict[str, Any], **user: Any) -> None:
    with pytest.raises(HouseError, match=match):
        layout(config, *extras, **user)


def room(name: str, at: list[int] | None = None, **fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "agent": "maker", **fields}
    if at is not None:
        out["at"] = at
    return out


def test_default_house_loads(config: Config) -> None:
    house = layout(config)
    assert [r.id for r in house.rooms] == DEFAULT_IDS
    assert all(r.kind == "default" for r in house.rooms)
    hall = house.room(HALL)
    assert (hall.at, hall.size, hall.agent, hall.floor, hall.wall) == (
        (1, 1),
        (2, 2),
        "host",
        "red-carpet",
        "teal-panel",
    )
    attic = house.room("attic")
    assert (attic.shape, attic.at, attic.agent) == ("round", (4, 0), "scout")
    block = {c for r in house.rooms if r.id != "attic" for c in r.cells()}
    assert block == {(x, y) for x in range(4) for y in range(4)}
    names = {a.id: a.name for a in house.agents.values()}
    assert names == {
        "host": "Vision",
        "steward": "Brass",
        "envoy": "Wren",
        "maker": "Tink",
        "checker": "Tock",
        "scout": "Rook",
    }


def test_default_files_exist(config: Config) -> None:
    house = layout(config)
    for agent in house.agents.values():
        assert (REPO / "house" / agent.persona).is_file(), agent.persona
    for name in TEXTURES:
        assert (REPO / "assets" / "textures" / f"{name}.png").is_file(), name


def test_host_follows_config(config: Config) -> None:
    config.assistant.name = "Ada"
    config.brain.talk_model = "talk-x"
    config.brain.heavy_model = "heavy-x"
    host = layout(config).agents["host"]
    assert (host.name, host.model, host.heavy_model) == ("Ada", "talk-x", "heavy-x")
    named = layout(config, agents={"host": {"name": "Max", "model": "m"}}).agents["host"]
    assert (named.name, named.model, named.heavy_model) == ("Max", "m", "heavy-x")


def test_personal_file_overrides(config: Config) -> None:
    house = layout(
        config,
        agents={"maker": {"name": "Sprocket", "model": "claude-haiku-5-5"}},
        rooms=[
            {
                "id": "garage",
                "name": "Platform",
                "agent": "checker",
                "folders": ["~/Projects/platform", "/srv/platform-api"],
                "model": "special-model",
                "floor": "stone-tile",
                "at": [0, 3],
            }
        ],
    )
    assert house.agents["maker"].name == "Sprocket"
    assert house.agents["maker"].persona == "agents/maker.md"
    garage = house.room("garage")
    assert (garage.name, garage.agent, garage.folders, garage.model, garage.floor) == (
        "Platform",
        "checker",
        ("~/Projects/platform", "/srv/platform-api"),
        "special-model",
        "stone-tile",
    )
    assert garage.wall == "stone-tile"


def test_config_agents_override(config: Config) -> None:
    config.agents = {"scout": {"model": "from-config"}}
    assert layout(config).agents["scout"].model == "from-config"


def test_default_rooms_cannot_move_or_reshape(config: Config) -> None:
    refused(config, "not moved", rooms=[{"id": "hall", "at": [2, 2]}])
    refused(config, "not moved", rooms=[{"id": "garage", "size": [2, 1]}])
    refused(config, "not moved", rooms=[{"id": "attic", "shape": "rect"}])


def test_room_without_position_goes_nearest_the_hall(config: Config) -> None:
    house = layout(config, room("Den"))
    den = house.room("den")
    assert den.kind == "extra"
    # The four cells nearest the Hall's centre all tie; the tie goes to reading order.
    assert den.at == (1, -1)
    big = layout(config, room("Studio", size=[2, 2])).room("studio")
    assert big.at == (1, -2)
    taken = layout(config, room("Den", at=[1, -1]), room("Nook")).room("nook")
    assert taken.at == (2, -1)


def test_extra_rooms_must_touch_the_house(config: Config) -> None:
    refused(config, "share a wall", room("Far", at=[8, 8]))
    refused(config, "share a wall", room("Corner", at=[-1, -1]))
    house = layout(config, room("Den", at=[4, 1]), room("Den East", at=[5, 1], size=[1, 2]))
    assert house.room("den-east").cells() == [(5, 1), (5, 2)]


def test_overlaps_are_refused(config: Config) -> None:
    refused(config, "overlaps 'Hall'", room("Den", at=[2, 2]))
    refused(config, "overlaps 'Den'", room("Den", at=[4, 1]), room("Bay", at=[4, 1]))


def test_room_size_rules(config: Config) -> None:
    assert layout(config, room("Long", at=[0, 4], size=[4, 1])).room("long").size == (4, 1)
    refused(config, "1 to 4", room("Big", at=[0, 4], size=[3, 2]))
    refused(config, "at least 1", room("Flat", at=[0, 4], size=[0, 1]))
    refused(config, "only the Attic is round", room("Tower", at=[0, 4], shape="round"))


def test_agent_rules(config: Config) -> None:
    refused(config, "not one of: host, steward", room("Den", at=[4, 1], agent="ghost"))
    refused(config, "exactly one agent", room("Den", at=[4, 1], agent=["host", "maker"]))
    refused(config, "needs a model", agents={"helper": {"name": "H", "persona": "p.md"}})
    refused(config, "needs a persona", agents={"helper": {"name": "H", "model": "m"}})
    added = layout(
        config,
        room("Den", at=[4, 1], agent="helper", model="room-model"),
        agents={"helper": {"name": "Helper", "persona": "agents/helper.md", "model": "m"}},
    )
    assert added.room("den").model == "room-model"


def test_twenty_extra_rooms_and_no_more(config: Config) -> None:
    slots = [(x, 4) for x in range(-1, 5)] + [(x, -1) for x in range(-1, 5)]
    slots += [(-1, y) for y in range(4)] + [(4, y) for y in range(1, 4)] + [(5, 0), (5, 1)]
    rooms = [room(f"Room {i}", at=list(cell)) for i, cell in enumerate(slots[:20])]
    assert len(layout(config, *rooms).extras()) == 20
    refused(config, "at most 20 extra rooms", *rooms, room("One more", at=list(slots[20])))


def test_ids_are_unique_slugs(config: Config) -> None:
    assert slugify("  Tea & Biscuits! ") == "tea-biscuits"
    house = layout(config, room("Library", at=[-1, 0]), room("Library", at=[-1, 1]))
    assert [r.id for r in house.extras()] == ["library-2", "library-3"]
    refused(
        config,
        "already taken",
        room("Den", at=[4, 1], id="spare"),
        room("X", at=[4, 2], id="spare"),
    )
    refused(config, "lowercase", room("Den", at=[4, 1], id="Not A Slug"))
    refused(config, "letters or digits", room("!!!", at=[4, 1]))
    refused(config, "appears twice", rooms=[{"id": "hall"}, {"id": "hall"}])


def test_values_are_checked(config: Config) -> None:
    refused(config, "floor must be one of", room("Den", at=[4, 1], floor="marble"))
    refused(config, "unknown setting 'colour'", room("Den", at=[4, 1], colour="red"))
    refused(config, "Unknown section 'room'", room=[{}])
    refused(config, "at must be two whole numbers", room("Den", at=[4]))
    refused(config, "needs a name", {"agent": "host", "at": [4, 1], "id": "den"})


def test_doors_connect_every_room_to_the_hall(config: Config) -> None:
    house = layout(
        config,
        room("Den", at=[4, 1]),
        room("Bay", at=[5, 1], size=[2, 2]),
        room("Porch", at=[0, 4], size=[4, 1]),
        room("Loft", at=[4, -1]),
    )
    occ = grid.occupancy(house.rooms)
    doors = grid.doors(house.rooms, occ)
    by_room = {d["a"]: d for d in doors}
    assert set(by_room) == {r.id for r in house.rooms} - {HALL}
    for door in doors:
        cell = (door["cell"][0], door["cell"][1])
        assert occ[cell] == door["a"]
        assert occ[grid.step(cell, str(door["side"]))] == door["b"]
    for start in by_room:
        seen, current = set(), start
        while current != HALL:
            assert current not in seen
            seen.add(current)
            current = str(by_room[current]["b"])
    assert by_room["control-room"] == {
        "a": "control-room",
        "b": "hall",
        "cell": [1, 0],
        "side": "s",
    }
    assert by_room["bay"]["b"] == "den"


def test_free_slots(config: Config) -> None:
    occ = grid.occupancy(layout(config).rooms)
    slots = grid.free_slots(occ)
    assert len(slots) == 17
    assert (5, 0) in slots and (4, -1) in slots
    assert (-1, -1) not in slots
    assert not set(slots) & occ.keys()
