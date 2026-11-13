"""Procedures: the store's rules, the file format, the prompt's listing, the four tools behind the
gate, and the owner's routes."""

from __future__ import annotations

import os
import stat
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from vision.core.bus import Bus
from vision.core.config import Config
from vision.gate.gate import ToolGate
from vision.procedures import NoSuchProcedure, ProcedureError, Procedures, build_tools, prompt_part
from vision.procedures.routes import build_router
from vision.procedures.store import OWN_MAX, SHARED_MAX, STEPS_MAX, slugify
from vision.procedures.tools import NAMES
from vision.testing.fakes import FakeMemory

TOKEN = "secret-token"


class Clock:
    """A minute later on every save, so "newest changed" is never a tie."""

    def __init__(self) -> None:
        self.t = datetime(2026, 11, 13, 10, 0).timestamp()

    def __call__(self) -> float:
        self.t += 60
        return self.t


@pytest.fixture
def changes() -> list[tuple[str, str, str]]:
    return []


@pytest.fixture
def store(tmp_path: Path, changes: list[tuple[str, str, str]]) -> Procedures:
    return Procedures(tmp_path / "house", lambda *c: changes.append(c), now=Clock())


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------ the store


def test_save_list_read_and_remove(store: Procedures, tmp_path: Path, changes: list[tuple[str, str, str]]) -> None:
    saved = store.save("maker", "Release the shop app", "Before tagging a release.", "1. Run the tests.\n2. Tag.")
    assert (saved.replaced, saved.moved, saved.shadows) == (False, False, False)
    p = saved.procedure
    assert (p.name, p.title, p.author, p.shared, p.opened) == ("release-the-shop-app", "Release the shop app", "maker", False, 0)
    path = tmp_path / "house/agents/maker/procedures/release-the-shop-app.md"
    assert path.read_text() == (
        "# Release the shop app\n\nWhen to use: Before tagging a release.\nAuthor: maker\n"
        "Changed: 2026-11-13 10:01\nOpened: 0\n\n## Steps\n\n1. Run the tests.\n2. Tag.\n"
    )
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [x.name for x in store.list("maker")] == ["release-the-shop-app"]
    assert store.list("checker") == []
    read = store.read("maker", "release the shop app")
    assert read.opened == 1 and read.steps == "1. Run the tests.\n2. Tag."
    assert store.read("maker", "Release-the-shop-app").opened == 2
    assert store.remove("maker", "release the shop app").title == "Release the shop app"
    assert store.list("maker") == [] and not path.exists()
    assert changes == [("maker", "release-the-shop-app", "saved"), ("maker", "release-the-shop-app", "removed")]
    assert not list(path.parent.glob(".*"))


def test_replacing_keeps_opened_and_moves_changed(store: Procedures) -> None:
    first = store.save("maker", "Deploy", "When deploying.", "Old steps.").procedure
    store.read("maker", "deploy")
    store.read("maker", "deploy")
    again = store.save("maker", "deploy", "When deploying the site.", "New steps.")
    assert again.replaced and again.procedure.opened == 2
    assert again.procedure.changed_at > first.changed_at
    assert store.read("maker", "deploy").steps == "New steps."


def test_slugs_and_loose_names(store: Procedures) -> None:
    assert slugify("  Release: the Shop/App!! ") == "release-the-shop-app"
    assert slugify("x" * 60) == "x" * 48
    assert slugify("Ünïcode ünly") == "n-code-nly"
    store.save("maker", "Check  the   Logs", "Daily.", "Look.")
    assert store.read("maker", "check the logs").title == "Check the Logs"
    assert store.read("maker", "CHECK-THE-LOGS").name == "check-the-logs"
    with pytest.raises(ProcedureError, match="at least one letter or digit"):
        store.save("maker", "!!!", "When.", "Steps.")
    with pytest.raises(NoSuchProcedure, match="no procedure called 'deploy'.*check-the-logs"):
        store.read("maker", "deploy")
    with pytest.raises(NoSuchProcedure, match="Say which"):
        store.read("maker", "  ")


def test_a_title_matches_when_the_file_name_does_not(store: Procedures, tmp_path: Path) -> None:
    write(tmp_path / "house/agents/maker/procedures/rel.md", "# Release the app\n\nDo it.")
    assert store.read("maker", "release the APP").name == "rel"


def test_limits_are_plain_refusals(store: Procedures) -> None:
    with pytest.raises(ProcedureError, match="name must be at most 80 characters"):
        store.save("maker", "n" * 81, "When.", "Steps.")
    with pytest.raises(ProcedureError, match="at most 300 characters"):
        store.save("maker", "Name", "w" * 301, "Steps.")
    with pytest.raises(ProcedureError, match="at most 6,000 characters"):
        store.save("maker", "Name", "When.", "s" * (STEPS_MAX + 1))
    with pytest.raises(ProcedureError, match="needs its steps"):
        store.save("maker", "Name", "When.", "  ")
    with pytest.raises(ProcedureError, match="needs a line on when"):
        store.save("maker", "Name", "", "Steps.")
    for i in range(OWN_MAX):
        store.save("maker", f"Own {i}", "When.", "Steps.")
    with pytest.raises(ProcedureError, match=f"already have {OWN_MAX} procedures"):
        store.save("maker", "One more", "When.", "Steps.")
    store.save("maker", "Own 3", "When, again.", "Better steps.")
    for i in range(SHARED_MAX):
        store.save("scout", f"Shared {i}", "When.", "Steps.", shared=True)
    with pytest.raises(ProcedureError, match=f"already {SHARED_MAX} shared procedures"):
        store.save("checker", "One more", "When.", "Steps.", shared=True)
    store.save("scout", "Shared 7", "When, again.", "Better.", shared=True)


def test_sharing_rules(store: Procedures, changes: list[tuple[str, str, str]]) -> None:
    store.save("maker", "Release", "When releasing.", "Steps.", shared=True)
    assert [p.name for p in store.list("checker")] == ["release"]
    assert store.read("checker", "release").author == "maker"
    with pytest.raises(ProcedureError, match="written by maker; only they or the host can change or remove it"):
        store.save("checker", "Release", "Mine.", "Other steps.", shared=True)
    with pytest.raises(ProcedureError, match="only they or the host"):
        store.remove("checker", "release")
    improved = store.save("maker", "Release", "When releasing.", "Better.", shared=True)
    assert improved.replaced and improved.procedure.opened == 1
    by_host = store.save("host", "Release", "When releasing.", "Host's.", shared=True).procedure
    assert by_host.author == "maker" and by_host.steps == "Host's."
    store.remove("host", "release")
    assert store.list("maker") == []
    assert changes[-1] == ("shared", "release", "removed")


def test_an_own_one_shadows_a_shared_one(store: Procedures) -> None:
    store.save("maker", "Release", "Shared.", "Shared steps.", shared=True)
    saved = store.save("checker", "Release", "Mine.", "My steps.")
    assert saved.shadows and not saved.procedure.shared
    assert [(p.name, p.shared) for p in store.list("checker")] == [("release", False)]
    assert store.read("checker", "release").steps == "My steps."
    assert store.read("scout", "release").steps == "Shared steps."
    store.remove("checker", "release")
    assert store.read("checker", "release").shared


def test_sharing_moves_the_own_copy(store: Procedures, tmp_path: Path, changes: list[tuple[str, str, str]]) -> None:
    store.save("maker", "Lint", "Before a commit.", "Run ruff.")
    store.read("maker", "lint")
    moved = store.save("maker", "Lint", "Before a commit.", "Run ruff.", shared=True)
    assert moved.moved and moved.procedure.opened == 1 and moved.procedure.author == "maker"
    assert not (tmp_path / "house/agents/maker/procedures/lint.md").exists()
    assert (tmp_path / "house/procedures/lint.md").is_file()
    assert [(p.name, p.shared) for p in store.list("maker")] == [("lint", True)]
    assert changes[-2:] == [("maker", "lint", "removed"), ("shared", "lint", "saved")]


def test_hand_written_files_still_read(store: Procedures, tmp_path: Path) -> None:
    folder = tmp_path / "house/agents/maker/procedures"
    write(folder / "plain.md", "# Water the plants\n\nFill the can.\nWater each pot.\n")
    write(folder / "no-heading.md", "Just some text.")
    write(
        folder / "broken.md",
        "# Broken\nWhen to use:   Sometimes \nOpened: lots\nChanged: yesterday\nAuthor: Someone Else!\n"
        "A loose line.\n## steps\n1. One.\n",
    )
    write(folder / "binary.md", "")
    (folder / "binary.md").write_bytes(b"\xff\xfe\x00")
    write(folder / ".hidden.md", "# Hidden")
    found = {p.name: p for p in store.list("maker")}
    assert set(found) == {"plain", "no-heading", "broken"}
    assert (found["plain"].title, found["plain"].when, found["plain"].steps) == (
        "Water the plants", "", "Fill the can.\nWater each pot.",
    )
    assert (found["no-heading"].title, found["no-heading"].steps) == ("no heading", "Just some text.")
    broken = found["broken"]
    assert (broken.when, broken.opened, broken.author, broken.steps) == ("Sometimes", 0, "maker", "A loose line.\n\n1. One.")
    assert broken.changed_at == pytest.approx((folder / "broken.md").stat().st_mtime)
    assert store.read("maker", "water the plants").opened == 1
    assert "Opened: 1" in (folder / "plain.md").read_text()
    assert store.read("maker", "plain").steps == "Fill the can.\nWater each pot."
    write(tmp_path / "house/procedures/common.md", "# Common\n\nAuthor: nobody here\n\nText.")
    assert store.read("maker", "common").author == "host"


def test_the_listing_keeps_to_its_room(store: Procedures) -> None:
    assert store.listing("maker", 1000) == ""
    store.save("maker", "Old one", "When old.", "Steps.")
    store.save("scout", "Search the web", "When looking things up.", "Steps.", shared=True)
    store.save("maker", "New one", "When new.", "Steps.")
    store.save("maker", "Mine shared", "When.", "Steps.", shared=True)
    assert store.listing("maker", 1000, {"scout": "Wren"}).split("\n") == [
        "- Mine shared (shared by you): When.",
        "- New one: When new.",
        "- Search the web (shared by Wren): When looking things up.",
        "- Old one: When old.",
    ]
    assert "(shared by scout)" in store.listing("maker", 1000)
    cut = store.listing("maker", 80)
    assert len(cut) <= 80
    assert cut.split("\n") == ["- Mine shared (shared by you): When.", "(3 more; list_procedures shows them all)"]
    part = prompt_part(store, "maker", 80)
    assert part.startswith("# Your procedures\n\nBefore you do a kind of work one of these covers")
    assert part.endswith("(3 more; list_procedures shows them all)")
    assert "saving one needs nobody's yes" in part
    assert prompt_part(store, "checker").endswith("- Search the web (shared by scout): When looking things up.")
    assert prompt_part(Procedures(store.folder("shared").parent / "empty"), "maker").endswith("\n\nNone yet.")


def test_the_owner_side(store: Procedures, changes: list[tuple[str, str, str]]) -> None:
    store.save("maker", "B task", "When.", "Steps.")
    store.save("maker", "A task", "When.", "Steps.")
    store.save("scout", "Shared", "When.", "Steps.", shared=True)
    own, shared = store.everything(["maker", "scout", "NOT AN ID"])
    assert [p.name for p in own["maker"]] == ["a-task", "b-task"] and own["scout"] == []
    assert [p.name for p in shared] == ["shared"] and "NOT AN ID" not in own
    assert store.get("maker", "a-task").opened == 0
    assert store.get("maker", "a-task").opened == 0
    edited = store.edit("shared", "shared", steps="Owner's steps.")
    assert (edited.author, edited.steps, edited.title) == ("scout", "Owner's steps.", "Shared")
    assert store.edit("maker", "a-task", title="A renamed task").name == "a-task"
    with pytest.raises(ProcedureError, match="Give a new title"):
        store.edit("maker", "a-task")
    with pytest.raises(ProcedureError, match="at most 80"):
        store.edit("maker", "a-task", title="t" * 90)
    for owner, name in (("maker", "nope"), ("../etc", "x"), ("maker", "../a-task")):
        with pytest.raises(NoSuchProcedure):
            store.get(owner, name)
    store.delete("shared", "shared")
    assert changes[-3:] == [("shared", "shared", "saved"), ("maker", "a-task", "saved"), ("shared", "shared", "removed")]


def test_agent_ids_are_checked(store: Procedures) -> None:
    with pytest.raises(ValueError, match="not an agent id"):
        store.save("../x", "Name", "When.", "Steps.")
    with pytest.raises(ValueError, match="not an agent id"):
        store.list("Maker")


# ------------------------------------------------------------ the tools


class Rig:
    def __init__(self, config: Config, agent: str = "maker") -> None:
        for name in NAMES:
            config.gate.tiers[name] = "free"
        self.memory = FakeMemory()
        self.store = Procedures(config.paths.house, now=Clock())
        self.gate = ToolGate(config, Bus(), self.memory, build_tools(self.store, agent, {"scout": "Wren"}))

    async def ok(self, tool: str, **args: object) -> str:
        result = await self.gate.call(tool, dict(args))
        assert result.ok, result.content
        return result.content

    async def refused(self, tool: str, **args: object) -> str:
        result = await self.gate.call(tool, dict(args))
        assert not result.ok
        return result.content


async def test_the_four_tools(config: Config) -> None:
    rig = Rig(config)
    assert [t.spec.name for t in build_tools(rig.store, "maker")] == list(NAMES)
    assert await rig.ok("list_procedures") == "You have no procedures yet, and none are shared."
    saved = await rig.ok("save_procedure", name="Release the shop", when="Before a release.", steps="1. Test.")
    assert saved == "Saved your procedure “Release the shop” (`release-the-shop`)."
    improved = await rig.ok("save_procedure", name="release the shop", when="Before a release.", steps="1. Test.\n2. Tag.")
    assert improved.startswith("Improved your procedure")
    rig.store.save("scout", "Search", "When searching.", "Look.", shared=True)
    listing = await rig.ok("list_procedures")
    assert "`release-the-shop` “release the shop” (your own; never opened" in listing
    assert "`search` “Search” (shared by Wren; never opened" in listing
    read = await rig.ok("read_procedure", name="Release the shop")
    assert "opened once" in read and read.endswith("Steps:\n1. Test.\n2. Tag.")
    shared = await rig.ok("save_procedure", name="Release the shop", when="Before.", steps="1. Test.", shared=True)
    assert "every agent sees it now. Your own copy became the shared one." in shared
    assert "no procedure called 'deploy'" in await rig.refused("read_procedure", name="deploy")
    assert "written by scout" in await rig.refused("remove_procedure", name="search")
    assert "needs its steps" in await rig.refused("save_procedure", name="X", when="When.", steps="")
    assert "true or false" in await rig.refused("save_procedure", name="X", when="W.", steps="S.", shared="yes")
    assert await rig.ok("remove_procedure", name="release the shop") == "Removed the shared procedure “Release the shop”."
    assert {a.tier for a in rig.memory.audits} == {"free"}


def test_cards_say_what_happens(tmp_path: Path) -> None:
    tools = {t.spec.name: t for t in build_tools(Procedures(tmp_path), "maker")}
    describe = tools["save_procedure"].describe
    assert describe is not None
    assert describe({"name": "Release the shop", "shared": True}) == "Save the procedure “Release the shop” (shared)"
    assert describe({"name": "Release the shop"}) == "Save the procedure “Release the shop”"
    assert "Before you do a kind" not in tools["read_procedure"].spec.description
    assert "nobody's yes" in tools["save_procedure"].spec.description


# ------------------------------------------------------------ the routes


@pytest.fixture
async def http(store: Procedures) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.state.token = TOKEN
    plan: list[dict[str, Any]] = [{"id": "host", "name": "Vision"}, {"id": "maker", "name": "Tink"}]
    app.include_router(build_router(store, lambda: plan), prefix="/api")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {TOKEN}"}
    ) as client:
        yield client


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/procedures"), ("GET", "/api/procedures/maker/x"), ("PUT", "/api/procedures/maker/x"),
     ("DELETE", "/api/procedures/maker/x")],
)
async def test_every_route_needs_the_token(http: httpx.AsyncClient, method: str, path: str) -> None:
    assert (await http.request(method, path, headers={"Authorization": ""})).status_code == 401


async def test_the_routes(http: httpx.AsyncClient, store: Procedures, changes: list[tuple[str, str, str]]) -> None:
    store.save("maker", "Release", "When releasing.", "1. Test.")
    store.save("scout", "Search", "When searching.", "Look.", shared=True)
    listing = (await http.get("/api/procedures")).json()
    assert [(a["id"], a["name"], len(a["procedures"])) for a in listing["agents"]] == [("host", "Vision", 0), ("maker", "Tink", 1)]
    assert set(listing["agents"][1]["procedures"][0]) == {
        "name", "title", "when", "author", "shared", "changed_at", "opened", "chars",
    }
    assert listing["shared"][0]["author"] == "scout" and listing["shared"][0]["shared"] is True
    assert listing["limits"] == {"name": 80, "when": 300, "steps": 6000, "per_agent": 40, "shared": 60}
    one = (await http.get("/api/procedures/maker/release")).json()["procedure"]
    assert one["steps"] == "1. Test." and one["chars"] == 8 and one["opened"] == 0
    edited = await http.put("/api/procedures/shared/search", json={"steps": "Look harder.", "title": "Search well"})
    assert edited.json()["procedure"]["steps"] == "Look harder." and edited.json()["procedure"]["author"] == "scout"
    assert (await http.put("/api/procedures/maker/release", json={"when": "w" * 400})).status_code == 400
    assert (await http.put("/api/procedures/maker/release", json={})).json()["detail"].startswith("Give a new title")
    assert (await http.put("/api/procedures/maker/release", json={"steps": 3})).status_code == 400
    assert (await http.put("/api/procedures/maker/release", content=b"[1]")).status_code == 400
    assert (await http.get("/api/procedures/maker/nothing")).status_code == 404
    assert (await http.get("/api/procedures/Not-An-Id/release")).status_code == 404
    assert (await http.put("/api/procedures/maker/nothing", json={"steps": "x"})).status_code == 404
    assert (await http.delete("/api/procedures/maker/release")).json() == {"removed": True}
    assert (await http.delete("/api/procedures/shared/search")).json() == {"removed": True}
    assert (await http.delete("/api/procedures/shared/search")).status_code == 404
    assert changes[-3:] == [("shared", "search", "saved"), ("maker", "release", "removed"), ("shared", "search", "removed")]
