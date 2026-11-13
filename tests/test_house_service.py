"""The live house: plan, changes, the user's file and hand edits."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import tomli_w

from vision.core.bus import Bus, Subscription
from vision.core.config import Config
from vision.core.events import Event, HouseChanged, Notice
from vision.house import GridHouse, HouseError, UnknownRoom, agent_models, make_house, store

PLAN_KEYS = {
    "revision",
    "cell_m",
    "wall_height_m",
    "max_extra_rooms",
    "assistant",
    "agents",
    "rooms",
    "doors",
    "free_slots",
}
ROOM_KEYS = {
    "id",
    "name",
    "kind",
    "shape",
    "at",
    "size",
    "agent",
    "model",
    "project",
    "floor",
    "wall",
    "tools",
    "state",
}


@pytest.fixture
async def house(config: Config) -> AsyncIterator[GridHouse]:
    h = GridHouse(config, Bus(), poll_s=0.02)
    yield h
    await h.close()


def watch(house: GridHouse) -> Subscription:
    return house._bus.subscribe(["house.changed", "notice"])


async def next_event(sub: Subscription, timeout: float = 2.0) -> Event:
    return await asyncio.wait_for(sub.get(), timeout)


def write_user(config: Config, doc: dict[str, Any]) -> None:
    config.paths.house_file.write_text(tomli_w.dumps(doc))


def test_factory_reads_nothing(config: Config) -> None:
    make_house(config, Bus())
    assert not config.paths.house_file.exists()


def test_plan_shape_and_first_use(config: Config) -> None:
    house = make_house(config, Bus())
    plan = house.plan()
    assert set(plan) == PLAN_KEYS
    assert plan["revision"] == 0
    assert (plan["cell_m"], plan["wall_height_m"], plan["max_extra_rooms"]) == (4.0, 2.6, 20)
    assert plan["assistant"] == {"name": "Vision"}
    assert plan["agents"][0] == {
        "id": "host",
        "name": "Vision",
        "model": "claude-haiku-5-5",
        "heavy_model": "claude-opus-5-5",
        "persona": "agents/host.md",
    }
    hall = plan["rooms"][0]
    assert set(hall) == ROOM_KEYS
    assert hall == {
        "id": "hall",
        "name": "Hall",
        "kind": "default",
        "shape": "rect",
        "at": [1, 1],
        "size": [2, 2],
        "agent": "host",
        "model": "claude-haiku-5-5",
        "project": None,
        "floor": "red-carpet",
        "wall": "teal-panel",
        "tools": [
            {"id": tool_id, "title": title, "available": True, "built_in": True}
            for tool_id, title in [
                ("remember", "Remember"),
                ("recall", "Recall"),
                ("open_app", "Open app"),
                ("open_url", "Open link"),
                ("shell", "Shell"),
                ("create_automation", "Schedule an automation"),
                ("list_automations", "List automations"),
                ("update_automation", "Change an automation"),
                ("pause_automation", "Pause an automation"),
                ("resume_automation", "Resume an automation"),
                ("run_automation", "Run an automation now"),
                ("delete_automation", "Delete an automation"),
                ("house_overview", "Describe the house"),
                ("room_details", "Describe a room"),
                ("assistant_status", "Check its own status"),
                ("hand_off", "Hand off work"),
                ("list_jobs", "List jobs"),
                ("job_details", "Look at a job"),
                ("cancel_job", "Cancel a job"),
            ]
        ],
        "state": "idle",
    }
    assert {r["state"] for r in plan["rooms"][1:]} == {"dark"}
    assert all(set(d) == {"a", "b", "cell", "side"} for d in plan["doors"])
    assert [4, 1] in plan["free_slots"]
    assert config.paths.house_file.read_bytes() == store.DEFAULT_FILE.read_bytes()


def test_room_model_is_resolved(config: Config) -> None:
    store.ensure_user_file(config.paths.house_file, store.DEFAULT_FILE)
    write_user(config, {"rooms": [{"id": "garage", "model": "claude-sonnet-5-5"}]})
    rooms = {r["id"]: r for r in make_house(config, Bus()).plan()["rooms"]}
    assert rooms["garage"]["model"] == "claude-sonnet-5-5"
    assert rooms["workshop"]["model"] == "claude-opus-5-5"


def test_set_room_state(config: Config) -> None:
    house = make_house(config, Bus())
    house.set_room_state("library", "active")
    house.set_room_state("hall", "dark")
    rooms = {r["id"]: r["state"] for r in house.plan()["rooms"]}
    assert (rooms["library"], rooms["hall"], rooms["kitchen"]) == ("active", "dark", "dark")
    with pytest.raises(UnknownRoom):
        house.set_room_state("nowhere", "idle")
    with pytest.raises(HouseError):
        house.set_room_state("hall", "blinding")  # type: ignore[arg-type]


async def test_add_room_writes_file_and_publishes(house: GridHouse, config: Config) -> None:
    sub = watch(house)
    room = await house.add_room({"name": "Studio", "agent": "maker", "project": "~/p"})
    assert room["id"] == "studio" and room["at"] == [1, -1] and room["kind"] == "extra"
    assert room["model"] == "claude-opus-5-5" and room["floor"] == "wood-floor"
    event = await next_event(sub)
    assert isinstance(event, HouseChanged) and event.revision == 1
    saved = store.read_toml(config.paths.house_file)
    assert saved["rooms"][-1] == {
        "name": "Studio",
        "agent": "maker",
        "project": "~/p",
        "id": "studio",
        "at": [1, -1],
    }
    fresh = make_house(config, Bus()).plan()
    assert [r["id"] for r in fresh["rooms"]][-1] == "studio"
    assert not list(config.paths.house_file.parent.glob(".house.toml.*"))


async def test_changes_are_validated(house: GridHouse) -> None:
    with pytest.raises(HouseError, match="share a wall"):
        await house.add_room({"name": "Far", "agent": "maker", "at": [9, 9]})
    with pytest.raises(HouseError, match="overlaps"):
        await house.add_room({"name": "Inside", "agent": "maker", "at": [1, 1]})
    with pytest.raises(HouseError, match="not one of"):
        await house.add_room({"name": "Den", "agent": "nobody"})
    with pytest.raises(HouseError, match="already taken"):
        await house.add_room({"name": "Hall two", "agent": "host", "id": "hall"})
    with pytest.raises(HouseError, match="Unknown setting 'shape'"):
        await house.add_room({"name": "Den", "agent": "maker", "shape": "round"})
    assert house.revision == 0


async def test_twenty_first_room_is_refused(house: GridHouse) -> None:
    for i in range(20):
        await house.add_room({"name": f"Room {i}", "agent": "maker"})
    assert house.revision == 20
    with pytest.raises(HouseError, match="at most 20 extra rooms"):
        await house.add_room({"name": "One too many", "agent": "maker"})
    assert len([r for r in house.plan()["rooms"] if r["kind"] == "extra"]) == 20


async def test_update_room(house: GridHouse, config: Config) -> None:
    room = await house.update_room(
        "garage", {"name": "Platform", "agent": "checker", "model": "m1", "wall": "wallpaper"}
    )
    assert (room["name"], room["agent"], room["model"], room["wall"]) == (
        "Platform",
        "checker",
        "m1",
        "wallpaper",
    )
    room = await house.update_room("garage", {"model": None})
    assert room["model"] == "claude-haiku-5-5"
    with pytest.raises(HouseError, match="not moved"):
        await house.update_room("garage", {"at": [5, 5]})
    with pytest.raises(HouseError, match="Nothing to change"):
        await house.update_room("garage", {})
    with pytest.raises(HouseError, match="cannot be empty"):
        await house.update_room("garage", {"name": None})
    with pytest.raises(UnknownRoom):
        await house.update_room("nowhere", {"name": "X"})
    await house.add_room({"name": "Den", "agent": "maker", "at": [4, 1]})
    moved = await house.update_room("den", {"at": [4, 2], "size": [2, 1]})
    assert (moved["at"], moved["size"]) == ([4, 2], [2, 1])
    garage = [t for t in store.read_toml(config.paths.house_file)["rooms"] if t["id"] == "garage"]
    assert garage[0]["name"] == "Platform" and "model" not in garage[0]


async def test_remove_room(house: GridHouse) -> None:
    await house.add_room({"name": "Den", "agent": "maker", "at": [4, 1]})
    await house.add_room({"name": "Nook", "agent": "maker", "at": [5, 1]})
    with pytest.raises(HouseError, match="would cut 'Nook' off from the Hall"):
        await house.remove_room("den")
    with pytest.raises(HouseError, match="cannot be removed"):
        await house.remove_room("library")
    with pytest.raises(UnknownRoom):
        await house.remove_room("nowhere")
    await house.remove_room("nook")
    await house.remove_room("den")
    assert [r["kind"] for r in house.plan()["rooms"]] == ["default"] * 10


async def test_hand_edit_is_picked_up(house: GridHouse, config: Config) -> None:
    house.plan()
    sub = watch(house)
    doc = store.read_toml(config.paths.house_file)
    doc["rooms"].append({"name": "Den", "agent": "maker", "at": [4, 1]})
    await asyncio.sleep(0.01)  # a distinct modification time
    write_user(config, doc)
    event = await next_event(sub)
    assert isinstance(event, HouseChanged) and event.revision == 1
    assert house.plan()["rooms"][-1]["id"] == "den"


async def test_bad_hand_edit_keeps_last_good_plan(house: GridHouse, config: Config) -> None:
    before = house.plan()
    sub = watch(house)
    config.paths.house_file.write_text("[[rooms]]\nname = 'Far'\nagent = 'maker'\nat = [9, 9]\n")
    event = await next_event(sub)
    assert isinstance(event, Notice) and event.level == "warn"
    assert "share a wall" in event.text and "stays as it was" in event.text
    assert house.plan() == before
    with pytest.raises(HouseError, match="cannot be changed until it is fixed"):
        await house.add_room({"name": "Den", "agent": "maker"})
    config.paths.house_file.write_text("this is = = not toml")
    event = await next_event(sub)
    assert isinstance(event, Notice) and "not valid TOML" in event.text
    write_user(config, {"rooms": [{"id": "hall", "name": "Great Hall"}]})
    event = await next_event(sub)
    assert isinstance(event, HouseChanged)
    assert house.plan()["rooms"][0]["name"] == "Great Hall"


async def test_broken_file_at_start_uses_default(config: Config) -> None:
    config.paths.house_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.house_file.write_text("[agents.host]\ncolour = 'blue'\n")
    bus = Bus()
    sub = bus.subscribe(["notice"])
    house = GridHouse(config, bus, poll_s=0.02)
    try:
        assert len(house.plan()["rooms"]) == 10
        event = await next_event(sub)
        assert isinstance(event, Notice) and "colour" in event.text
        assert "Using the default house" in event.text
    finally:
        await house.close()


def test_agent_models(config: Config) -> None:
    assert agent_models(config, "host") == ("claude-haiku-5-5", "claude-opus-5-5")
    assert agent_models(config, "maker") == ("claude-opus-5-5", None)
    assert not config.paths.house_file.exists()
    config.brain.talk_model = "talk-x"
    assert agent_models(config, "host").model == "talk-x"
    config.paths.house_file.parent.mkdir(parents=True)
    write_user(config, {"agents": {"maker": {"model": "mine", "heavy_model": "mine-heavy"}}})
    assert agent_models(config, "maker") == ("mine", "mine-heavy")
    config.paths.house_file.write_text("not toml = =")
    assert agent_models(config, "maker").model == "claude-opus-5-5"
    with pytest.raises(KeyError):
        agent_models(config, "nobody")


HOST_REFUSAL = (
    "Vision orchestrates from the Hall and cannot run another room. "
    "Choose one of: Brass, Wren, Tink, Tock, Rook."
)
HALL_REFUSAL = "Vision orchestrates from the Hall, so the Hall cannot be given to another agent."


async def test_host_cannot_run_a_new_room(house: GridHouse) -> None:
    with pytest.raises(HouseError) as exc:
        await house.add_room({"name": "Den", "agent": "host"})
    assert str(exc.value) == HOST_REFUSAL
    assert house.revision == 0


async def test_host_cannot_take_over_a_room(house: GridHouse) -> None:
    with pytest.raises(HouseError) as exc:
        await house.update_room("library", {"agent": "host"})
    assert str(exc.value) == HOST_REFUSAL
    assert house.revision == 0


async def test_hall_cannot_be_given_to_another_agent(house: GridHouse) -> None:
    with pytest.raises(HouseError) as exc:
        await house.update_room("hall", {"agent": "maker"})
    assert str(exc.value) == HALL_REFUSAL
    assert house.revision == 0
    room = await house.update_room("hall", {"agent": "host", "name": "Great Hall"})
    assert room["agent"] == "host"


async def test_host_refusal_names_the_assistant_by_its_display_name(config: Config) -> None:
    config.assistant.name = "Ada"
    house = GridHouse(config, Bus(), poll_s=0.02)
    try:
        with pytest.raises(HouseError, match="^Ada orchestrates from the Hall"):
            await house.add_room({"name": "Den", "agent": "host"})
    finally:
        await house.close()


async def test_file_giving_host_another_room_is_rejected_on_load(config: Config) -> None:
    config.paths.house_file.parent.mkdir(parents=True, exist_ok=True)
    write_user(config, {"rooms": [{"id": "library", "agent": "host"}]})
    bus = Bus()
    sub = bus.subscribe(["notice"])
    house = GridHouse(config, bus, poll_s=0.02)
    try:
        rooms = {r["id"]: r["agent"] for r in house.plan()["rooms"]}
        assert rooms["library"] == "steward"
        event = await next_event(sub)
        assert isinstance(event, Notice) and event.level == "warn"
        assert HOST_REFUSAL in event.text and "Using the default house" in event.text
    finally:
        await house.close()


async def test_hand_edit_giving_host_another_room_keeps_last_good_plan(
    house: GridHouse, config: Config
) -> None:
    before = house.plan()
    sub = watch(house)
    write_user(config, {"rooms": [{"name": "Den", "agent": "host", "at": [4, 1]}]})
    event = await next_event(sub)
    assert isinstance(event, Notice) and HOST_REFUSAL in event.text
    assert "stays as it was" in event.text
    assert house.plan() == before


def test_default_house_gives_the_host_only_the_hall(config: Config) -> None:
    rooms = GridHouse(config, Bus()).plan()["rooms"]
    assert [r["id"] for r in rooms if r["agent"] == "host"] == ["hall"]
