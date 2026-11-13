"""The library's and the profile's routes, the owner in Settings, and how backups and
resets carry both, through the real server on the fake brain."""

from __future__ import annotations

from urllib.parse import quote

import pytest
from library_fixtures import blank_pdf, docx_with, pdf_with
from settings_fakes import client, use

from vision.app import Daemon
from vision.memory import profile
from vision.memory.documents import Library

ROUTES = [
    ("GET", "/api/library"),
    ("POST", "/api/library/files"),
    ("POST", "/api/library/text"),
    ("GET", "/api/library/documents/x"),
    ("PATCH", "/api/library/documents/x"),
    ("DELETE", "/api/library/documents/x"),
    ("GET", "/api/profile"),
    ("PATCH", "/api/profile"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_every_route_needs_the_token(daemon: Daemon, method: str, path: str) -> None:
    async with client(daemon, token=False) as http:
        assert (await http.request(method, path)).status_code == 401


def upload(name: str, data: bytes) -> dict[str, object]:
    return {"content": data, "headers": {"X-File-Name": quote(name), "Content-Type": "application/octet-stream"}}


async def test_adding_reading_renaming_and_removing(daemon: Daemon) -> None:
    async with client(daemon) as http:
        empty = (await http.get("/api/library")).json()
        pdf = await http.post("/api/library/files", **upload("Q3 report.pdf", pdf_with("Revenue rose 12 percent.")))
        word = await http.post("/api/library/files", **upload("Payment terms.docx", docx_with("Within 30 days.")))
        pasted = await http.post("/api/library/text", json={"title": "Prices", "text": "Sourdough 6 EUR."})
        listing = (await http.get("/api/library")).json()
        opened = (await http.get("/api/library/documents/q3-report")).json()
        renamed = await http.patch("/api/library/documents/prices", json={"title": "Price list"})
        removed = await http.delete("/api/library/documents/payment-terms")
        after = (await http.get("/api/library")).json()
    assert empty["documents"] == [] and empty["folder"] == str(daemon.config.paths.house / "library")
    assert empty["limits"]["endings"] == [".docx", ".markdown", ".md", ".pdf", ".text", ".txt"]
    assert pdf.status_code == 200 and pdf.json()["document"]["kind"] == "pdf"
    assert word.json()["document"]["title"] == "Payment terms"
    assert pasted.json()["document"]["kind"] == "note" and pasted.json()["document"]["editable"] is True
    assert [d["name"] for d in listing["documents"]] == ["prices", "payment-terms", "q3-report"]
    assert set(listing["documents"][0]) == {
        "name", "title", "kind", "chars", "bytes", "parts", "added_at", "gist", "original", "editable",
    }
    assert opened["text"] == "Revenue rose 12 percent." and opened["document"]["original"] == "originals/q3-report.pdf"
    assert renamed.json()["document"]["title"] == "Price list"
    assert removed.json()["removed"]["name"] == "payment-terms"
    assert [d["name"] for d in after["documents"]] == ["prices", "q3-report"]


async def test_refusals_come_back_beside_the_action(daemon: Daemon) -> None:
    async with client(daemon) as http:
        scan = await http.post("/api/library/files", **upload("scan.pdf", blank_pdf()))
        nameless = await http.post("/api/library/files", content=b"text")
        odd = await http.post("/api/library/files", **upload("photo.jpg", b"\xff\xd8"))
        untitled = await http.post("/api/library/text", json={"title": "", "text": "x"})
        missing = await http.get("/api/library/documents/nothing-here")
        rename_missing = await http.patch("/api/library/documents/nothing-here", json={"title": "x"})
        no_title = await http.post("/api/library/text", json={"title": "Prices", "text": "Sourdough."})
        bad_rename = await http.patch("/api/library/documents/prices", json={})
        not_json = await http.post("/api/library/text", content=b"[1]")
    assert scan.status_code == 400 and "scanned pages" in scan.json()["detail"]
    assert nameless.status_code == 400 and "X-File-Name" in nameless.json()["detail"]
    assert odd.status_code == 400 and "Word (.docx)" in odd.json()["detail"]
    assert untitled.status_code == 400 and "title must be" in untitled.json()["detail"]
    assert missing.status_code == 404 and rename_missing.status_code == 404
    assert no_title.status_code == 200
    assert bad_rename.status_code == 400 and "title must be" in bad_rename.json()["detail"]
    assert not_json.status_code == 400


async def test_a_file_past_the_cap_is_refused_unread(daemon: Daemon, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vision.memory.routes.MAX_FILE_BYTES", 10)
    async with client(daemon) as http:
        answer = await http.post("/api/library/files", **upload("big.txt", b"x" * 100))
    assert answer.status_code == 400 and "the most the library takes" in answer.json()["detail"]
    assert Library(daemon.config.paths.house).list() == []


async def test_the_profile_route(daemon: Daemon) -> None:
    async with client(daemon) as http:
        first = (await http.get("/api/profile")).json()
        changed = await http.patch("/api/profile", json={"name": "Sam", "business": "A bakery."})
        partial = await http.patch("/api/profile", json={"notes": "Closed on Mondays."})
        refused = await http.patch("/api/profile", json={"name": "a\nb"})
    assert first == {"profile": {"name": "", "business": "", "notes": ""}}
    assert changed.json()["profile"]["name"] == "Sam"
    assert partial.json()["profile"] == {"name": "Sam", "business": "A bakery.", "notes": "Closed on Mondays."}
    assert refused.status_code == 400 and "one line" in refused.json()["detail"]


async def test_the_owner_in_settings(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        saved = (await http.patch("/api/settings", json={"owner": {"name": "Sam", "business": "A bakery."}})).json()
        again = (await http.patch("/api/settings", json={"owner": {"name": "Sam", "notes": "Speak German."}})).json()
        bad = await http.patch("/api/settings", json={"owner": {"name": "x" * 61, "age": 3}, "assistant": {"name": ""}})
        got = (await http.get("/api/settings")).json()
    assert saved["changed"] == ["owner.name", "owner.business"] and saved["applied"] == saved["changed"]
    assert again["changed"] == ["owner.notes"]
    assert got["owner"] == {"name": "Sam", "business": "A bakery.", "notes": "Speak German."}
    fields = {e["field"] for e in bad.json()["detail"]["errors"]}
    assert bad.status_code == 400 and fields == {"owner.name", "owner.age", "assistant.name"}
    assert profile.read(daemon.config.paths.house).notes == "Speak German."
    assert not daemon.config.paths.config_file.exists() or "owner" not in daemon.config.paths.config_file.read_text()


async def test_the_host_has_the_tools_and_hears_who_the_owner_is(daemon: Daemon) -> None:
    names = [s.name for s in daemon.components.tools.specs()]
    assert names[5:12] == [
        "update_profile", "list_documents", "read_document", "search_documents",
        "add_document", "update_document", "remove_document",
    ]
    profile.update(daemon.config.paths.house, {"name": "Sam", "business": "A bakery."})
    assert "- The owner, as of now (this replaces anything said earlier): Sam; their business: A bakery." in daemon.surroundings()


async def test_backups_and_resets_carry_the_profile_and_documents(daemon: Daemon) -> None:
    use(daemon)
    house = daemon.config.paths.house
    async with client(daemon) as http:
        await http.patch("/api/profile", json={"name": "Sam"})
        await http.post("/api/library/files", **upload("terms.docx", docx_with("Within 30 days.")))
        kept = (await http.post("/api/reset", json={"level": "settings"})).json()
        assert profile.read(house).name == "Sam" and len(Library(house).list()) == 1
        wiped = (await http.post("/api/reset", json={"level": "everything"})).json()
        after = (await http.get("/api/library")).json()
        owner = (await http.get("/api/profile")).json()
        restored = (await http.post(f"/api/backups/{wiped['backup']['id']}/restore")).json()
        back = (await http.get("/api/library")).json()
    assert kept["backup"]["level"] == "settings"
    assert "what it knew about you and your library's documents" in wiped["message"]
    saved = daemon.config.paths.home / "backups" / wiped["backup"]["id"] / "house"
    assert (saved / "owner.md").is_file() and (saved / "library" / "originals" / "terms.docx").is_file()
    assert after["documents"] == [] and owner["profile"]["name"] == ""
    assert "house" in restored["restored"]
    assert [d["name"] for d in back["documents"]] == ["terms"] and profile.read(house).name == "Sam"
    assert Library(house).search("days")[0].document.name == "terms"
