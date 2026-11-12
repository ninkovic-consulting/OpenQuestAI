"""The house routes through the real server, with the token."""

import asyncio

import httpx
import pytest

from vision.app import Daemon
from vision.core.events import HouseChanged
from vision.house import GridHouse


def client(d: Daemon, *, token: bool = True) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {d.token}"} if token else {}
    return httpx.AsyncClient(base_url=f"http://127.0.0.1:{d.port}", headers=headers)


async def test_daemon_uses_the_grid_house(daemon: Daemon) -> None:
    assert isinstance(daemon.components.house, GridHouse)
    async with client(daemon) as http:
        plan = (await http.get("/api/house")).json()
    assert plan["revision"] == 0
    assert [r["id"] for r in plan["rooms"]][:2] == ["hall", "library"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/house/agents"),
        ("POST", "/api/house/rooms"),
        ("PATCH", "/api/house/rooms/hall"),
        ("DELETE", "/api/house/rooms/den"),
    ],
)
async def test_routes_need_the_token(daemon: Daemon, method: str, path: str) -> None:
    async with client(daemon, token=False) as http:
        assert (await http.request(method, path, json={})).status_code == 401


async def test_agents(daemon: Daemon) -> None:
    async with client(daemon) as http:
        agents = (await http.get("/api/house/agents")).json()["agents"]
    assert [a["id"] for a in agents] == ["host", "steward", "envoy", "maker", "checker", "scout"]
    assert [a["name"] for a in agents] == ["Vision", "Brass", "Wren", "Tink", "Tock", "Rook"]


async def test_add_edit_remove(daemon: Daemon) -> None:
    sub = daemon.bus.subscribe(["house.changed"])
    async with client(daemon) as http:
        added = await http.post(
            "/api/house/rooms", json={"name": "Den", "agent": "maker", "at": [4, 1]}
        )
        assert added.status_code == 201
        assert added.json()["revision"] == 1 and added.json()["room"]["id"] == "den"
        event = await asyncio.wait_for(sub.get(), 2)
        assert isinstance(event, HouseChanged) and event.revision == 1

        edited = await http.patch(
            "/api/house/rooms/den", json={"name": "Snug", "floor": "red-carpet"}
        )
        assert edited.status_code == 200
        assert edited.json()["room"]["name"] == "Snug"

        renamed = await http.patch("/api/house/rooms/hall", json={"name": "Great Hall"})
        assert renamed.json()["room"]["name"] == "Great Hall"

        assert (await http.delete("/api/house/rooms/den")).json() == {"revision": 4}
        plan = (await http.get("/api/house")).json()
    assert plan["revision"] == 4
    assert "den" not in {r["id"] for r in plan["rooms"]}
    assert daemon.config.paths.house_file.is_file()


async def test_errors_are_actionable(daemon: Daemon) -> None:
    async with client(daemon) as http:
        far = await http.post(
            "/api/house/rooms", json={"name": "Far", "agent": "maker", "at": [9, 9]}
        )
        assert far.status_code == 400
        assert "must share a wall" in far.json()["detail"]
        ghost = await http.post("/api/house/rooms", json={"name": "Den", "agent": "ghost"})
        assert ghost.status_code == 400 and "not one of" in ghost.json()["detail"]
        assert (await http.post("/api/house/rooms", content=b"[1, 2]")).status_code == 400
        assert (await http.post("/api/house/rooms", content=b"{oops")).status_code == 400
        move = await http.patch("/api/house/rooms/hall", json={"at": [5, 5]})
        assert move.status_code == 400 and "not moved" in move.json()["detail"]
        remove = await http.delete("/api/house/rooms/hall")
        assert remove.status_code == 400 and "cannot be removed" in remove.json()["detail"]
        assert (await http.patch("/api/house/rooms/nowhere", json={"name": "X"})).status_code == 404
        assert (await http.delete("/api/house/rooms/nowhere")).status_code == 404
        for i in range(20):
            ok = await http.post("/api/house/rooms", json={"name": f"Room {i}", "agent": "maker"})
            assert ok.status_code == 201
        full = await http.post("/api/house/rooms", json={"name": "One more", "agent": "maker"})
        assert full.status_code == 400 and "at most 20" in full.json()["detail"]
