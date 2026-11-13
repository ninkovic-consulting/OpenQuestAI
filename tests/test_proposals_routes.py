"""The owner's routes for proposals and made tools: the token, the shapes, the order, 400 and 404."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from test_proposals import SCRIPT, World, build_world, tool_fields

from vision.proposals.routes import build_router

TOKEN = "route-test-token"

ROUTES = [
    ("get", "/api/proposals"),
    ("get", "/api/proposals/x"),
    ("post", "/api/proposals/x/approve"),
    ("post", "/api/proposals/x/decline"),
    ("post", "/api/proposals/x/restore"),
    ("get", "/api/made-tools"),
    ("get", "/api/made-tools/x"),
    ("patch", "/api/made-tools/x"),
    ("post", "/api/made-tools/x/versions/1/use"),
    ("delete", "/api/made-tools/x"),
]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(tmp_path)


@pytest.fixture
async def http(world: World) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.state.token = TOKEN
    app.include_router(build_router(world.proposals), prefix="/api")
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_every_route_needs_the_token(http: httpx.AsyncClient, method: str, path: str) -> None:
    answer = await http.request(method, path, headers={"Authorization": "Bearer wrong"})
    assert answer.status_code == 401


async def test_listing_order_and_shapes(world: World, http: httpx.AsyncClient) -> None:
    long_persona = "You are Tink. " * 40
    first = await world.proposals.propose_tool(world.tink, tool_fields(name="first_tool"))
    second = await world.proposals.propose_change(world.tink, "persona", long_persona, "Clearer.")
    third = await world.proposals.propose_tool(world.host, tool_fields(name="third_tool", folders=[]))
    fourth = await world.proposals.propose_change(world.host, "model", "claude-opus-5-5", "Smarter.")
    await world.proposals.decline(first.id)
    await world.proposals.approve(fourth.id)
    body = (await http.get("/api/proposals?limit=10")).json()
    assert [p["id"] for p in body["proposals"]] == [second.id, third.id, fourth.id, first.id]
    assert body["waiting"] == 2 and body["limits"] == {"per_agent": 3, "total": 12, "script_max": 20_000}
    summary = body["proposals"][1]
    assert "script" not in summary["tool"] and summary["tool"]["sha256"] and summary["clipped"] is False
    persona = body["proposals"][0]
    assert persona["clipped"] is True and len(persona["change"]["after"]) == 300
    detail = (await http.get(f"/api/proposals/{second.id}")).json()["proposal"]
    assert detail["change"]["after"] == long_persona and "clipped" not in detail
    tool_detail = (await http.get(f"/api/proposals/{third.id}")).json()["proposal"]
    assert tool_detail["tool"]["script"] == SCRIPT and tool_detail["tool"]["tool_name"] == "made_third_tool"
    assert set(tool_detail) == {
        "id", "kind", "status", "agent", "agent_name", "job", "room", "title", "reason", "created_at",
        "decided_at", "note", "tool", "change", "decision", "restored_at",
    }
    assert [p["id"] for p in (await http.get("/api/proposals?limit=1")).json()["proposals"]] == [second.id]
    assert (await http.get("/api/proposals?limit=0")).status_code == 422


async def test_deciding_through_the_routes(world: World, http: httpx.AsyncClient) -> None:
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    assert (await http.post("/api/proposals/nope/approve")).status_code == 404
    bad = await http.post(f"/api/proposals/{made.id}/approve", json={"who": "anyone"})
    assert bad.status_code == 400 and "author or everyone" in bad.json()["detail"]
    odd = await http.post(f"/api/proposals/{made.id}/approve", json={"colour": "red"})
    assert odd.status_code == 400 and "'colour'" in odd.json()["detail"]
    not_object = await http.post(f"/api/proposals/{made.id}/approve", content=b"[1]")
    assert not_object.status_code == 400
    done = await http.post(f"/api/proposals/{made.id}/approve", json={"who": "everyone", "tier": "free"})
    assert done.status_code == 200
    assert done.json()["proposal"]["decision"] == {"who": "everyone", "tier": "free"}
    again = await http.post(f"/api/proposals/{made.id}/decline", json={"note": "late"})
    assert again.status_code == 400 and "already approved" in again.json()["detail"]
    restore = await http.post(f"/api/proposals/{made.id}/restore")
    assert restore.status_code == 400 and "Only an approved change" in restore.json()["detail"]
    change = await world.proposals.propose_change(world.tink, "model", "claude-opus-5-5", "Faster.")
    declined = await http.post(f"/api/proposals/{change.id}/decline", json={"note": "Not now."})
    assert declined.json()["proposal"]["status"] == "declined" and declined.json()["proposal"]["note"] == "Not now."
    other = await world.proposals.propose_change(world.tink, "effort", "high", "Careful.")
    await http.post(f"/api/proposals/{other.id}/approve")
    restored = (await http.post(f"/api/proposals/{other.id}/restore")).json()["proposal"]
    assert restored["restored_at"] is not None
    assert world.settings_calls[-1] == {"agents": {"maker": {"effort": "medium"}}}


async def test_a_refused_change_is_a_400_and_stays_waiting(world: World, http: httpx.AsyncClient) -> None:
    from vision.settings import values

    made = await world.proposals.propose_change(world.tink, "model", "claude-unknown-1", "Try it.")
    world.settings_error.append(values.Invalid([{"field": "agents", "message": "Unknown model."}]))
    answer = await http.post(f"/api/proposals/{made.id}/approve")
    assert answer.status_code == 400 and answer.json()["detail"] == "Unknown model."
    assert (await http.get(f"/api/proposals/{made.id}")).json()["proposal"]["status"] == "waiting"


async def test_made_tool_routes(world: World, http: httpx.AsyncClient) -> None:
    made = await world.proposals.propose_tool(world.tink, tool_fields())
    await http.post(f"/api/proposals/{made.id}/approve")
    world.problem[0] = None
    listing = (await http.get("/api/made-tools")).json()
    [tool] = listing["tools"]
    assert tool["name"] == "count_lines" and tool["status"] == "enabled" and tool["tier"] == "ask"
    assert listing["confinement"]["available"] is True and listing["confinement"]["reason"] is None
    assert listing["confinement"]["enforced"] and listing["confinement"]["not_enforced"]
    one = (await http.get("/api/made-tools/count_lines")).json()
    assert one["tool"]["script"] == SCRIPT and one["tool"]["versions"][0]["script"] == SCRIPT and one["runs"] == []
    assert (await http.get("/api/made-tools/nope")).status_code == 404
    patched = await http.patch("/api/made-tools/count_lines", json={"tier": "free", "who": "everyone", "enabled": False})
    assert patched.json()["tool"]["tier"] == "free" and patched.json()["tool"]["status"] == "disabled"
    assert (await http.patch("/api/made-tools/count_lines", json={"tier": "never"})).status_code == 400
    assert (await http.patch("/api/made-tools/count_lines", json={"script": "x"})).status_code == 400
    used = await http.post("/api/made-tools/count_lines/versions/1/use")
    assert used.status_code == 200 and used.json()["tool"]["status"] == "enabled"
    assert (await http.post("/api/made-tools/count_lines/versions/7/use")).status_code == 404
    (world.home / "made-tools" / "count_lines" / "versions" / "1.py").write_text("print(1)\n")
    assert (await http.get("/api/made-tools")).json()["tools"][0]["status"] == "changed"
    assert (await http.patch("/api/made-tools/count_lines", json={"enabled": True})).status_code == 400
    assert (await http.delete("/api/made-tools/count_lines")).json() == {"removed": True}
    assert (await http.delete("/api/made-tools/count_lines")).status_code == 404
