import asyncio
import dataclasses
import json
import stat

import httpx
import pytest
from conftest import all_fakes
from fastapi import APIRouter
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from vision.app import Components, Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import Hello, InputText
from vision.core.server import allowed_origins
from vision.core.token import ensure_token
from vision.testing.fakes import FakeHouse


def base(d: Daemon) -> str:
    return f"http://127.0.0.1:{d.port}"


def auth(d: Daemon) -> dict[str, str]:
    return {"Authorization": f"Bearer {d.token}"}


def test_token_file_is_private_and_stable(config: Config) -> None:
    token = ensure_token(config.paths.token)
    assert len(token) >= 32
    assert stat.S_IMODE(config.paths.token.stat().st_mode) == 0o600
    assert ensure_token(config.paths.token) == token


def test_allowed_origins() -> None:
    assert allowed_origins("127.0.0.1", 7341) == {
        "http://127.0.0.1:7341",
        "http://localhost:7341",
    }


@pytest.mark.parametrize("path", ["/api/health", "/api/state", "/api/history", "/api/house"])
async def test_http_requires_token(daemon: Daemon, path: str) -> None:
    async with httpx.AsyncClient(base_url=base(daemon)) as client:
        assert (await client.get(path)).status_code == 401
        wrong = {"Authorization": "Bearer nope"}
        assert (await client.get(path, headers=wrong)).status_code == 401
        assert (await client.get(path, headers={"Authorization": daemon.token})).status_code == 401
        assert (await client.get(path, headers=auth(daemon))).status_code == 200


async def test_http_rejects_foreign_origin(daemon: Daemon) -> None:
    async with httpx.AsyncClient(base_url=base(daemon), headers=auth(daemon)) as client:
        foreign = await client.get("/api/health", headers={"Origin": "http://evil.example"})
        assert foreign.status_code == 403
        rebound = await client.get("/api/health", headers={"Origin": f"http://evil.example:{daemon.port}"})
        assert rebound.status_code == 403
        own = await client.get("/api/health", headers={"Origin": base(daemon)})
        assert own.status_code == 200
        assert own.json()["ok"] is True
        assert (await client.get("/", headers={"Origin": "http://evil.example"})).status_code == 403


async def test_state_and_index(daemon: Daemon) -> None:
    async with httpx.AsyncClient(base_url=base(daemon), headers=auth(daemon)) as client:
        state = (await client.get("/api/state")).json()
        assert state["state"] == "idle"
        assert state["brain"] == "fake"
        assert set(state["budget"]) == {"month", "spent_usd", "cap_usd"}
        assert {"level": "info", "text": "Running on the fake brain (--fake-brain)."} in state[
            "notices"
        ]
        plan = (await client.get("/api/house")).json()
        assert len(plan["rooms"]) == 10 and len(plan["agents"]) == 6
        index = await client.get("/", headers={})
        assert index.status_code == 200
        assert "Vision is running" in index.text


async def test_ws_bad_token_closes(daemon: Daemon) -> None:
    url = f"ws://127.0.0.1:{daemon.port}/ws"
    async with connect(url) as ws:
        await ws.send(Hello(token="wrong").to_json())
        with pytest.raises(ConnectionClosed) as info:
            await ws.recv()
    assert info.value.rcvd is not None and info.value.rcvd.code == 4401


async def test_ws_first_message_must_be_hello(daemon: Daemon) -> None:
    async with connect(f"ws://127.0.0.1:{daemon.port}/ws") as ws:
        await ws.send(InputText(text="hi").to_json())
        with pytest.raises(ConnectionClosed) as info:
            await ws.recv()
    assert info.value.rcvd is not None and info.value.rcvd.code == 4401


async def test_ws_foreign_origin_refused(daemon: Daemon) -> None:
    with pytest.raises(InvalidStatus) as info:
        async with connect(f"ws://127.0.0.1:{daemon.port}/ws", origin="http://evil.example"):  # type: ignore[arg-type]
            pass
    assert info.value.response.status_code == 403


async def test_ws_good_token_and_bad_message(daemon: Daemon) -> None:
    async with connect(f"ws://127.0.0.1:{daemon.port}/ws", origin=base(daemon)) as ws:  # type: ignore[arg-type]
        await ws.send(Hello(token=daemon.token).to_json())
        await ws.send('{"type": "vision.reply", "ts": 0, "data": {"text": "x", "turn_id": "t"}}')
        reply = json.loads(await ws.recv())
        assert reply["type"] == "notice" and "not a window event" in reply["data"]["text"]
        await ws.send("garbage")
        reply = json.loads(await ws.recv())
        assert reply["type"] == "notice" and reply["data"]["level"] == "warn"


async def test_house_router_is_mounted_behind_auth(config: Config) -> None:
    router = APIRouter()

    @router.get("/rooms")
    async def rooms() -> list[str]:
        return ["hall"]

    class RoutedHouse(FakeHouse):
        @property
        def router(self) -> APIRouter:
            return router

    def parts(bus: Bus) -> Components:
        return dataclasses.replace(all_fakes(bus), house=RoutedHouse())

    d = Daemon(config, port=7399, components=parts)
    transport = httpx.ASGITransport(app=d.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7399") as client:
        assert (await client.get("/api/house/rooms")).status_code == 401
        ok = await client.get("/api/house/rooms", headers=auth(d))
        assert ok.json() == ["hall"]
        foreign = await client.get(
            "/api/house/rooms", headers={**auth(d), "Origin": "http://evil.example"}
        )
        assert foreign.status_code == 403


async def test_window_closing_its_socket_is_not_an_error(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    for _ in range(3):
        async with connect(f"ws://127.0.0.1:{daemon.port}/ws") as ws:
            await ws.send(Hello(token=daemon.token).to_json())
            await ws.send(InputText(text="hi").to_json())
            await ws.recv()
    await asyncio.sleep(0.3)
    assert "Exception in ASGI application" not in caplog.text
